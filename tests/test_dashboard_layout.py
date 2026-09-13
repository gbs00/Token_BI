"""Rendered viewport checks using isolated backend fixtures, never real accounts."""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["chromium", "webkit"])
def layout_page(app, request):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        engine = getattr(runtime, request.param)
        if not Path(engine.executable_path).exists():
            pytest.skip(f"{request.param} not installed")
        browser = engine.launch(headless=True)
        page = browser.new_page(viewport={"width": 568, "height": 320}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_default_timeout(5000)
        client = TestClient(app, base_url="http://tokenbi.test")

        def serve(route):
            response = client.get(urlsplit(route.request.url).path)
            route.fulfill(body=response.content, status=response.status_code,
                          content_type=response.headers.get("content-type", "text/plain"))

        page.route("http://tokenbi.test/**", serve)
        page.add_init_script("""window.payload = {
          state:'ready', message:null, account:{masked_email:'demo****@example.com'},
          summary:{source_type:'oauth',last_success_at:new Date().toISOString()},
          metrics:[{metric_type:'session',remaining_pct:100,reset_at:new Date(Date.now()+14400000).toISOString()},
                   {metric_type:'weekly',remaining_pct:82,reset_at:new Date(Date.now()+600000000).toISOString()}]
        }; window.fetch = () => Promise.resolve(new Response(JSON.stringify(window.payload)));
        """)
        yield page, request.param
        browser.close()
        assert not errors


def wait_layout(page):
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    page.wait_for_function("""() => {
      const viewport=window.visualViewport;
      const expectedHeight=Math.floor(viewport ? viewport.height : innerHeight);
      if ((!viewport || viewport.scale === 1) && document.querySelector('.dashboard-shell').getBoundingClientRect().height !== expectedHeight) return false;
      const rings=[...document.querySelectorAll('.metric-radial')];
      return rings.length > 0 && rings.every(el => parseInt(el.style.width) ===
        Math.floor(Math.min(el.parentElement.clientWidth,el.parentElement.clientHeight,360)));
    }""")


def geometry(page):
    return page.evaluate("""() => {
      const box = el => el.getBoundingClientRect();
      const cards = [...document.querySelectorAll('.quota-card')];
      const contains = (outer, inner) => inner.left >= outer.left - 1 && inner.right <= outer.right + 1 &&
        inner.top >= outer.top - 1 && inner.bottom <= outer.bottom + 1;
      return {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
        bounds: [...document.querySelectorAll('.dashboard-shell,.topbar,.main,.quota-grid,.quota-body,.metric-radial,.reset-row')].map(el =>
          ({name:el.className,y:box(el).y,height:box(el).height,bottom:box(el).bottom})),
        rows: cards.map(el => box(el).top),
        cardWidths: cards.map(el => box(el).width),
        rings: cards.map(card => {
          const radial = card.querySelector('.metric-radial'), r = box(radial), body = box(card.querySelector('.quota-body'));
          const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
          const labelFits = [...radial.querySelectorAll('.metric-radial-inner > *')].every(el => {
            const b = box(el);
            return [[b.left,b.top],[b.right,b.top],[b.left,b.bottom],[b.right,b.bottom]].every(([x,y]) =>
              Math.hypot(x-cx,y-cy) <= r.width * .37 + 1);
          });
          return {width:r.width,height:r.height,styleWidth:radial.style.width,parentHeight:radial.parentElement.clientHeight,labelFits,contained:contains(body,r),
            separated:box(card.querySelector('.quota-head')).bottom <= r.top &&
              r.bottom <= box(card.querySelector('.reset-row')).top,
            resetFont:parseFloat(getComputedStyle(card.querySelector('.reset-time')).fontSize)};
        })
      };
    }""")


@pytest.mark.parametrize("width,height", [(568,320),(667,375),(844,390),(844,320),(896,414),(932,430),
                                         (1024,768),(1920,1080),(320,568),(390,844),(430,932),(768,1024)])
@pytest.mark.parametrize("count", [1, 2])
def test_normal_quota_fits_one_viewport(layout_page, width, height, count):
    page, engine = layout_page
    page.set_viewport_size({"width": width, "height": height})
    if count == 1:
        page.add_init_script("window.payload.metrics.splice(0,1)")
    page.goto("http://tokenbi.test/dashboard")
    wait_layout(page)
    result = geometry(page)
    assert result["width"] <= width, result
    assert result["height"] <= height + 1, result
    if count == 2:
        assert abs(result["cardWidths"][0] - result["cardWidths"][1]) < 1
        assert (abs(result["rows"][0] - result["rows"][1]) < 1) == (width > height)
    for ring in result["rings"]:
        assert ring["width"] == ring["height"] >= 128
        assert ring["contained"] and ring["separated"] and ring["labelFits"], result
        assert ring["resetFont"] >= 14
    if os.getenv("TOKEN_BI_VISUAL_QA") == "1" and (width,height) in [(568,320),(844,390),(390,844),(1920,1080)]:
        output = ROOT / "docs/design-previews/dashboard-qa"
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / f"{engine}-{width}x{height}-{count}.png"))


def test_rotation_and_metric_count_changes_reflow_without_fetching_for_resize(layout_page):
    page, _ = layout_page
    page.add_init_script("window.reads=0; window.fetch=()=>{window.reads++; return Promise.resolve(new Response(JSON.stringify(window.payload)));};")
    page.goto("http://tokenbi.test/dashboard")
    wait_layout(page)
    reads = page.evaluate("window.reads")
    for width,height in [(390,844),(844,390),(568,320)]:
        page.set_viewport_size({"width":width,"height":height})
        wait_layout(page)
        result = geometry(page)
        assert result["height"] <= height + 1, result
    assert page.evaluate("window.reads") == reads
    page.evaluate("window.payload.metrics.splice(0,1)")
    page.locator('[data-refresh-link]').click()
    page.wait_for_function("document.querySelectorAll('.quota-card').length===1")
    wait_layout(page)
    assert geometry(page)["height"] <= 321


def test_legacy_resize_fallback_without_modern_viewport_apis(layout_page):
    page, _ = layout_page
    page.add_init_script("Object.defineProperty(window,'visualViewport',{value:undefined}); window.ResizeObserver=undefined;")
    page.goto("http://tokenbi.test/dashboard")
    wait_layout(page)
    page.set_viewport_size({"width":844,"height":320})
    wait_layout(page)
    assert page.evaluate("document.documentElement.style.getPropertyValue('--viewport-height')") == "320px"
    assert geometry(page)["height"] <= 321


def test_browser_chrome_resize_and_pinch_zoom_are_distinguished(layout_page):
    page, _ = layout_page
    page.set_viewport_size({"width":844,"height":390})
    page.add_init_script("window.testViewport=new EventTarget(); Object.assign(testViewport,{height:390,scale:1}); Object.defineProperty(window,'visualViewport',{value:testViewport});")
    page.goto("http://tokenbi.test/dashboard")
    wait_layout(page)
    page.evaluate("testViewport.height=320; testViewport.dispatchEvent(new Event('resize'))")
    wait_layout(page)
    assert page.locator('.dashboard-shell').bounding_box()["height"] == 320
    assert page.locator('.quota-grid').bounding_box()["y"] + page.locator('.quota-grid').bounding_box()["height"] <= 320
    size = page.locator('.metric-radial').first.bounding_box()["width"]
    page.evaluate("testViewport.scale=2; testViewport.height=160; testViewport.dispatchEvent(new Event('resize'))")
    wait_layout(page)
    assert page.locator('.dashboard-shell').bounding_box()["height"] == 320
    assert page.locator('.metric-radial').first.bounding_box()["width"] == size


def test_long_error_and_tiny_height_scroll_instead_of_clipping(layout_page):
    page, _ = layout_page
    page.set_viewport_size({"width":568,"height":240})
    page.add_init_script("window.payload.message='暂时无法连接，请检查网络，稍后将自动重试。'.repeat(8)")
    page.goto("http://tokenbi.test/dashboard")
    wait_layout(page)
    result = geometry(page)
    assert result["height"] > 240
    assert result["width"] <= 568
    assert all(r["contained"] and r["separated"] for r in result["rings"])
    page.locator('.reset-row').last.scroll_into_view_if_needed()
    assert page.locator('.reset-row').last.bounding_box()["y"] < 240


def test_dark_landscape_keeps_insets_and_official_ring_ratio(layout_page):
    page, engine = layout_page
    page.set_viewport_size({"width":844,"height":390})
    page.goto("http://tokenbi.test/dashboard?theme=dark")
    # Model reserved horizontal/bottom space; native safe-area behavior still needs device QA.
    page.add_style_tag(content=".topbar{padding-left:44px;padding-right:44px}.main{padding-left:44px;padding-right:44px;padding-bottom:21px}")
    wait_layout(page)
    result = geometry(page)
    assert result["height"] <= 391 and result["width"] <= 844
    assert all(r["labelFits"] and r["contained"] for r in result["rings"])
    rings = page.locator('[data-metric-ring-value]')
    assert float(rings.nth(0).get_attribute('stroke-dashoffset')) == 0
    assert abs(float(rings.nth(1).get_attribute('stroke-dashoffset')) - 263.89378290154264 * .18) < .001
    if os.getenv("TOKEN_BI_VISUAL_QA") == "1":
        output = ROOT / "docs/design-previews/dashboard-qa"
        output.mkdir(exist_ok=True)
        page.screenshot(path=str(output / f"{engine}-dark-insets.png"))
