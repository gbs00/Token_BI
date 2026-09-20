import os
from pathlib import Path

import pytest
from test_desktop_shell import panel  # noqa: F401

pytestmark = pytest.mark.parametrize("panel", ["chromium", "webkit"], indirect=True)


def setup_resets(page, count=1):
    page.add_init_script("""window.payload.dashboard.reset_credits={available_count:3,
      expires_at:[506,19320,20880].map(m=>new Date(Date.now()+m*60000+59000).toISOString())};
      window.payload.dashboard.metrics[0].reset_at=new Date(Date.now()+498600000).toISOString();""")
    if count == 2:
        page.add_init_script("window.payload.dashboard.metrics.unshift({metric_type:'session',label:'5h 额度',remaining_pct:99,reset_at:new Date(Date.now()+7200000).toISOString()})")


@pytest.mark.parametrize("count", [1, 2])
def test_reset_row_fits_without_scrolling_and_preserves_actions(panel, count):
    setup_resets(panel, count)
    errors = []
    panel.on("pageerror", lambda e: errors.append(str(e)))
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#reset-credits h2").inner_text() == "存储重置"
    assert panel.locator("#reset-credits").get_attribute("aria-label") == "存储重置"
    assert panel.locator("#reset-credits-count").count() == 0
    assert "次可用" not in panel.locator("#reset-credits").inner_text()
    assert panel.locator("#reset-credits-empty").is_hidden()
    assert panel.locator("#reset-credits-times > span").all_text_contents() == ["8h 26m", "13d 10h", "14d 12h"]
    assert panel.evaluate("document.querySelector('.scroll-body').scrollHeight <= document.querySelector('.scroll-body').clientHeight + 1")
    assert panel.evaluate("[...document.querySelectorAll('#reset-credits, #reset-credits-times > span')].every(e=>e.getBoundingClientRect().right <= innerWidth-16)")
    assert panel.locator("#reset-credits").bounding_box()["y"] > panel.locator("#metrics").bounding_box()["y"]
    assert panel.locator('[data-action="qr"]').bounding_box()["y"] > panel.locator("#reset-credits").bounding_box()["y"]
    assert panel.locator('[data-action="open_local"]').bounding_box()["y"] < 540
    assert not errors
    if os.getenv("TOKEN_BI_RESET_QA") == "1":
        output = Path("/tmp/token-bi-reset-qa")
        output.mkdir(exist_ok=True)
        panel.screenshot(path=str(output / f"resets-{count}-{panel.context.browser.browser_type.name}.png"))


def test_expiry_updates_locally_and_logout_hides_credits(panel):
    panel.clock.install()
    panel.add_init_script("window.payload.dashboard.reset_credits={available_count:3,expires_at:[new Date(Date.now()+1000).toISOString(),null]}")
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#reset-credits-times > span").all_text_contents() == ["不足 1m", "2 次到期未知"]
    panel.clock.run_for(2100)
    assert panel.locator("#reset-credits-times > span").all_text_contents() == ["2 次到期未知"]
    assert panel.locator("#reset-credits-empty").is_hidden()
    assert panel.evaluate("calls.filter(c=>c[1]==='status').length") == 1
    panel.locator('[data-action="logout"]').click()
    panel.locator("#confirm-button").click()
    assert panel.locator("#reset-credits").is_hidden()


def test_zero_and_unsupported_are_distinct(panel):
    panel.clock.install()
    panel.add_init_script("window.payload.dashboard.reset_credits={available_count:0,expires_at:[]}")
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#reset-credits-empty").is_visible()
    assert panel.locator("#reset-credits-empty").inner_text() == "暂无可用重置"
    assert panel.locator("#reset-expirations").is_hidden()
    panel.evaluate("window.payload.dashboard.reset_credits=null;window.dispatchEvent(new Event('focus'))")
    panel.locator("#reset-credits").wait_for(state="hidden")


def test_last_expiry_switches_to_empty_state(panel):
    panel.clock.install()
    panel.add_init_script("window.payload.dashboard.reset_credits={available_count:1,expires_at:[new Date(Date.now()+1000).toISOString()]}")
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#reset-credits-empty").is_hidden()
    panel.clock.run_for(2100)
    assert panel.locator("#reset-credits-empty").is_visible()
    assert panel.locator("#reset-expirations").is_hidden()
    assert panel.locator("#reset-credits-times > span").count() == 0


def test_short_screen_and_many_expirations_wrap_inside_scroll_area(panel):
    panel.set_viewport_size({"width": 311, "height": 400})
    panel.add_init_script("window.payload.dashboard.reset_credits={available_count:12,expires_at:Array.from({length:12},(_,i)=>new Date(Date.now()+(i+1)*86400000).toISOString())}")
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#reset-credits-times > span").count() == 12
    assert panel.evaluate("document.documentElement.scrollWidth===innerWidth")
    panel.locator('[data-action="qr"]').scroll_into_view_if_needed()
    assert panel.locator('[data-action="qr"]').is_visible()
    assert panel.locator("footer").bounding_box()["y"] < 370
