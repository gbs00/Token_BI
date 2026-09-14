"""Exercise the bundled popover with an isolated IPC bridge, never real credentials."""
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1] / "desktop"


@pytest.fixture
def panel(request):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        param = getattr(request, "param", 1)
        engine = getattr(runtime, param if isinstance(param, str) else "chromium")
        if not Path(engine.executable_path).exists():
            pytest.skip(f"{engine.name} not installed")
        browser = engine.launch(headless=True)
        page = browser.new_page(viewport={"width": 311, "height": 600}, device_scale_factor=param if isinstance(param, int) else 1, reduced_motion="reduce")
        def serve(route):
            urlpath = urlsplit(route.request.url).path
            previews = ROOT.parent / "docs/design-previews"
            if urlpath in {"/comparison.html", "/design-reference.png"}:
                path = previews / ("menubar-comparison.html" if urlpath.endswith("html") else "menubar-choice-1.png")
                route.fulfill(body=path.read_bytes(), content_type="text/html" if urlpath.endswith("html") else "image/png")
                return
            path = (ROOT / urlsplit(route.request.url).path.lstrip("/")).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file():
                route.abort()
                return
            route.fulfill(body=path.read_bytes(), content_type=mimetypes.guess_type(path)[0] or "text/plain")
        page.route("**/*", serve)
        page.add_init_script("""
          window.calls = []; window.visible = true;
          window.payload = {healthy:true, account:{status:'active',masked_email:'demo****@example.com'},
            dashboard:{state:'ready', account:{status:'active',masked_email:'demo****@example.com'},
              metrics:[{metric_type:'weekly',label:'周额度',remaining_pct:99}],summary:{source_type:'oauth'}}};
          window.__TAURI__ = {core:{invoke:async (command,args={}) => {
            window.calls.push([command,args.action]);
            if(command==='panel_state') { const open_qr=window.openQR; window.openQR=false;
              return {phase:window.phase || 'ready',message:'启动失败测试',visible:window.visible,open_qr,update:window.updateState}; }
            if(command==='update_action') {
              window.updateState={...window.updateState,phase:{check:'checking',download:'downloading',install:'installing'}[args.action]};
            }
            if(command==='panel_action' && args.action==='status') return window.payload;
            if(command==='panel_action' && args.action==='refresh') return {ok:false,message:'网络超时'};
            if(command==='panel_action' && args.action?.startsWith('qr_')) return window.qrPayloads[args.action.slice(3)];
            if(command==='panel_action' && args.action==='logout') window.payload={healthy:true,access_enabled:false};
            return {ok:true};
          }}};
        """)
        page.set_default_timeout(5000)
        yield page
        browser.close()


def test_single_quota_uses_threshold_color_without_fabricating_session(panel):
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator(".metric").count() == 1
    assert "tier-high" in panel.locator(".metric").get_attribute("class")
    assert panel.locator(".bar-fill").get_attribute("style") == "width: 99%;"
    assert panel.locator(".metric-value").text_content() == "99%剩余"


def test_failed_refresh_keeps_quota_and_never_claims_success(panel):
    panel.goto("http://tokenbi.test/index.html")
    panel.locator('[data-action="refresh"]').click()
    assert "网络超时" in panel.locator("#feedback").inner_text()
    assert "额度已同步" not in panel.locator("#feedback").inner_text()
    assert panel.locator(".metric").count() == 1


@pytest.mark.parametrize("panel", [1, 2], indirect=True)
@pytest.mark.parametrize("remaining", [0, 9, 99, 100])
def test_quota_typography_separates_number_unit_and_suffix_without_overflow(panel, remaining):
    panel.add_init_script(f"window.payload.dashboard.metrics[0].remaining_pct={remaining};")
    panel.goto("http://tokenbi.test/index.html")
    panel.locator(".metric-number").wait_for()
    assert panel.locator(".metric-number").inner_text() == str(remaining)
    assert panel.locator(".metric-unit").inner_text() == "%"
    assert panel.locator(".bar-fill").get_attribute("style") == f"width: {remaining}%;"
    sizes = panel.evaluate("""() => {
      const value = document.querySelector('.metric-value');
      const elements = [...value.children];
      const boxes = elements.map(el => el.getBoundingClientRect());
      const heading = document.querySelector('.metric-heading').getBoundingClientRect();
      return {
        fonts: elements.map(el => parseFloat(getComputedStyle(el).fontSize)),
        alignment: getComputedStyle(value).alignItems,
        fits: boxes.every((box, index) => box.top >= heading.top && box.bottom <= heading.bottom + 1 &&
          box.right <= heading.right && (index === 0 || boxes[index - 1].right <= box.left)),
        labelSeparate: document.querySelector('.metric h2').getBoundingClientRect().right <= value.getBoundingClientRect().left
      };
    }""")
    assert sizes["fonts"][0] > sizes["fonts"][1] == sizes["fonts"][2]
    assert sizes["alignment"] == "baseline"
    assert sizes["fits"] and sizes["labelSeparate"]
    if os.getenv("TOKEN_BI_VISUAL_QA") == "1" and remaining == 100:
        panel.screenshot(path=str(ROOT.parent / "docs/design-previews/menubar-qa" / f"quota-100-dpr{panel.evaluate('devicePixelRatio')}.png"))


def test_logout_requires_confirmation_and_clears_cached_identity(panel):
    panel.goto("http://tokenbi.test/index.html")
    panel.locator('[data-action="logout"]').click()
    assert panel.locator("#confirm-dialog").is_visible()
    assert panel.evaluate("calls.filter(c=>c[1]==='logout').length") == 0
    panel.locator("#confirm-button").click()
    panel.locator("#login").wait_for(state="visible")
    assert panel.locator(".metric").count() == 0
    assert panel.locator("#account").is_hidden()


def test_hidden_panel_does_not_poll_backend_or_stop_service(panel):
    panel.add_init_script("window.visible=false")
    panel.clock.install()
    panel.goto("http://tokenbi.test/index.html")
    panel.clock.run_for(20000)
    assert panel.evaluate("calls.filter(c=>c[1]==='status').length") == 0
    panel.evaluate("window.visible=true")
    panel.clock.run_for(2000)
    assert panel.evaluate("calls.filter(c=>c[1]==='status').length") == 1
    panel.keyboard.press("Escape")
    assert panel.evaluate("calls.some(c=>c[0]==='panel_hide')")
    assert not panel.evaluate("calls.some(c=>c[0]==='panel_quit' || c[1]==='stop')")


def test_boot_failure_is_inline_and_retry_does_not_open_new_window(panel):
    panel.add_init_script("window.phase='error'")
    panel.goto("http://tokenbi.test/index.html")
    assert "启动失败测试" in panel.locator("#notice").inner_text()
    panel.locator('[data-action="retry"]').click()
    assert panel.evaluate("calls.some(c=>c[1]==='retry_start')")


def test_cold_tray_qr_request_survives_frontend_initialization(panel):
    panel.add_init_script("window.openQR=true")
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#qr").is_visible()
    assert panel.locator("#home").is_hidden()
    panel.locator('[data-action="back"]').click()
    panel.evaluate("window.dispatchEvent(new Event('focus'))")
    assert panel.locator("#home").is_visible()


@pytest.mark.parametrize("access_enabled", [True, False])
def test_backend_outage_preserves_only_connected_account_snapshot(panel, access_enabled):
    panel.clock.install()
    panel.add_init_script("window.payload.dashboard.account.account_id='acc_current';window.payload.account.account_id='acc_current'")
    panel.goto("http://tokenbi.test/index.html")
    panel.locator(".metric").wait_for()
    panel.evaluate("""enabled => { window.payload={healthy:false,running:true,access_enabled:enabled,
        account:{account_id:'acc_current',status:'active'},dashboard:null,health_error:'状态接口未响应'}; }""", access_enabled)
    panel.clock.run_for(16000)
    assert "状态接口未响应" in panel.locator("#notice").inner_text()
    assert panel.locator(".metric").count() == (1 if access_enabled else 0)


def test_stopped_backend_has_restart_action(panel):
    panel.add_init_script("window.payload={running:false,healthy:false}")
    panel.goto("http://tokenbi.test/index.html")
    panel.locator('[data-action="retry"]').click()
    assert panel.evaluate("calls.some(c=>c[1]==='retry_start')")


@pytest.mark.parametrize("width,height", [(311,600),(308,480),(311,400)])
def test_compact_layout_keeps_footer_and_buttons_inside_viewport(panel,width,height):
    panel.set_viewport_size({"width":width,"height":height})
    panel.goto("http://tokenbi.test/index.html")
    assert panel.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert panel.locator("footer").bounding_box()["y"] < height - 30
    assert panel.locator(".metric-value").bounding_box()["width"] < width / 2


@pytest.mark.parametrize("panel", [1, 2], indirect=True)
@pytest.mark.parametrize("width,height", [(311, 600), (311, 404), (308, 388)])
def test_logical_layout_is_stable_at_both_backing_scales(panel, width, height):
    panel.set_viewport_size({"width": width, "height": height})
    panel.goto("http://tokenbi.test/index.html")
    panel.locator(".metric-value").wait_for()
    result = panel.evaluate("""() => {
      const box = element => element.getBoundingClientRect();
      const title = document.querySelector('.brand h1');
      const label = document.querySelector('.metric h2');
      const value = document.querySelector('.metric-value');
      return {
        panelWidth: box(document.querySelector('.panel')).width,
        titleHeight: box(title).height,
        metricHeight: box(label).height,
        separated: box(label).right <= box(value).left,
        footerFits: [...document.querySelectorAll('footer button')].every(button =>
          box(button).left >= 0 && box(button).right <= innerWidth &&
          box(button).bottom <= innerHeight && button.scrollWidth <= button.clientWidth),
        rootBackground: getComputedStyle(document.documentElement).backgroundColor,
        rootClip: getComputedStyle(document.documentElement).overflow,
        rootRadius: getComputedStyle(document.documentElement).borderTopLeftRadius
      };
    }""")
    assert result["panelWidth"] == width
    assert result["titleHeight"] < 30
    assert result["metricHeight"] < 26
    assert result["separated"] and result["footerFits"]
    assert result["rootBackground"] == "rgba(0, 0, 0, 0)"
    assert result["rootClip"] == "hidden" and result["rootRadius"] == "12px"


@pytest.mark.parametrize("count", [1, 2])
def test_311px_home_keeps_account_and_actions_visible_without_scrolling(panel, count):
    panel.add_init_script("""window.payload.account.masked_email='guob****@gmail.com';
      window.payload.dashboard.account.masked_email='guob****@gmail.com';
      window.payload.dashboard.metrics=[{metric_type:'weekly',label:'周额度',remaining_pct:100}];""")
    if count == 2:
        panel.add_init_script("window.payload.dashboard.metrics.unshift({metric_type:'session',label:'5h 额度',remaining_pct:100});")
    panel.goto("http://tokenbi.test/index.html")
    panel.locator(".metric").last.wait_for()
    assert panel.locator(".metric").count() == count
    assert panel.evaluate("document.querySelector('#email').scrollWidth <= document.querySelector('#email').clientWidth")
    assert panel.evaluate("document.querySelector('.scroll-body').scrollHeight <= document.querySelector('.scroll-body').clientHeight + 1")
    assert panel.locator('[data-action="open_local"]').bounding_box()["y"] < 540


@pytest.mark.parametrize("kind", ["lan", "fixed"])
def test_311px_pairing_keeps_square_qr_and_actions_visible(panel, kind):
    import qrcode
    import qrcode.image.svg

    urls = {"lan": "http://192.168.31.167:8787/dashboard", "fixed": "http://gbs00MacBook-Air-M2.local:8787/dashboard"}
    payloads = {name: {"ok": True, "url": url, "svg": qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage).to_string().decode()} for name, url in urls.items()}
    panel.add_init_script(f"window.payload.urls={json.dumps(urls)};window.qrPayloads={json.dumps(payloads)};")
    panel.goto("http://tokenbi.test/index.html")
    panel.locator('[data-action="qr"]').click()
    panel.locator(f'[data-kind="{kind}"]').click()
    panel.locator("#qr-image").wait_for(state="visible")
    assert panel.locator("#qr-url").inner_text() == urls[kind]
    qr = panel.locator("#qr-image").bounding_box()
    assert qr["width"] == qr["height"] == 200
    assert panel.evaluate("document.querySelector('.scroll-body').scrollHeight <= document.querySelector('.scroll-body').clientHeight + 1")
    assert panel.locator('[data-action="open_selected"]').bounding_box()["y"] < 540
    if os.getenv("TOKEN_BI_VISUAL_QA") == "1":
        panel.screenshot(path=str(ROOT.parent / "docs/design-previews/menubar-qa" / f"compact-qr-{kind}.png"))


def test_visual_evidence_matches_selected_two_window_layout(panel):
    panel.add_init_script("""
      window.payload.dashboard.metrics = [
        {metric_type:'session',label:'5h 额度',remaining_pct:82,reset_at:new Date(Date.now()+13139000).toISOString()},
        {metric_type:'weekly',label:'周额度',remaining_pct:44,reset_at:new Date(Date.now()+291659000).toISOString()}];
      window.payload.dashboard.summary.last_success_at = new Date().toISOString();
    """)
    panel.set_viewport_size({"width":800,"height":796})
    panel.goto("http://tokenbi.test/comparison.html")
    frame = panel.frame_locator("iframe")
    frame.locator(".metric").nth(1).wait_for(state="visible")
    assert frame.locator(".metric-value").all_text_contents() == ["82%剩余", "44%剩余"]
    assert frame.locator(".metric").nth(0).bounding_box()["height"] == frame.locator(".metric").nth(1).bounding_box()["height"]
    if os.getenv("TOKEN_BI_VISUAL_QA") != "1":
        return
    outputs = ROOT.parent / "docs/design-previews/menubar-qa"
    outputs.mkdir(exist_ok=True)
    panel.screenshot(path=str(outputs / "comparison-normal.png"))
    panel.set_viewport_size({"width":311,"height":600})
    panel.goto("http://tokenbi.test/index.html")
    panel.locator(".metric").nth(1).wait_for(state="visible")
    panel.screenshot(path=str(outputs / "normal.png"))
    panel.set_viewport_size({"width":308,"height":480})
    panel.screenshot(path=str(outputs / "compact.png"))
