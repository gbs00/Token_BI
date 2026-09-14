"""Update UI and onboarding use an isolated bridge, without network or accounts."""
import json
import os
from pathlib import Path
import pytest

from test_desktop_shell import panel  # noqa: F401

pytestmark = pytest.mark.parametrize("panel", ["chromium", "webkit"], indirect=True)


def screenshot(page, name):
    if os.getenv("TOKEN_BI_UPDATE_QA") == "1":
        output = Path(__file__).resolve().parents[1] / "docs/design-previews/v121-qa/production"
        output.mkdir(exist_ok=True)
        engine = page.context.browser.browser_type.name
        page.screenshot(path=str(output / f"{name}-{engine}.png"))


def test_onboarding_is_ready_before_backend_and_only_acknowledges_user_action(panel):
    panel.set_viewport_size({"width": 284, "height": 214})
    panel.goto("http://tokenbi.test/onboarding.html")
    panel.wait_for_function("calls.some(c=>c[0]==='onboarding_action' && c[1]==='ready')")
    assert "我在这里哦" in panel.locator("h1").inner_text()
    assert not panel.evaluate("calls.some(c=>c[0]==='panel_action')")
    assert panel.evaluate("document.documentElement.scrollHeight <= innerHeight")
    screenshot(panel, "onboarding")
    panel.locator('[data-action="open"]').click()
    assert panel.evaluate("calls.some(c=>c[0]==='onboarding_action' && c[1]==='open')")


def test_updates_keep_badge_when_hidden_and_require_explicit_install(panel):
    panel.clock.install()
    panel.add_init_script("window.updateState={phase:'available',available:true,current_version:'1.2.1',version:'1.2.2',notes:'<img src=x onerror=alert(1)>'}")
    panel.goto("http://tokenbi.test/index.html")
    assert panel.locator("#update-dot").is_visible()
    panel.locator("#settings-button").click()
    assert panel.locator("#update-action span").inner_text() == "立即更新"
    panel.locator("#toggle-notes").click()
    assert panel.locator("#notes-copy img").count() == 0
    assert "<img" in panel.locator("#notes-copy").inner_text()
    panel.locator("#update-action").click()
    assert panel.locator("#update-action").is_disabled()
    panel.evaluate("window.visible=false; window.updateState={...window.updateState,phase:'ready'}")
    panel.clock.run_for(2000)
    assert panel.evaluate("calls.filter(c=>c[0]==='update_action' && c[1]==='download').length") == 1
    assert not panel.evaluate("calls.some(c=>c[0]==='update_action' && c[1]==='install')")
    assert panel.locator("#update-dot").is_visible()
    panel.evaluate("window.visible=true")
    panel.clock.run_for(2000)
    assert panel.locator("#update-action span").inner_text() == "重启完成更新"
    panel.locator("#update-later").click()
    assert panel.locator("#home").is_visible()
    panel.locator("#settings-button").click()
    panel.locator("#update-action").click()
    assert panel.evaluate("calls.filter(c=>c[0]==='update_action' && c[1]==='install').length") == 1


@pytest.mark.parametrize("phase", ["idle", "checking", "latest", "available", "downloading", "ready", "installing", "check_error", "download_error", "install_error"])
@pytest.mark.parametrize("height", [600, 400])
def test_update_states_fit_compact_panel_with_accessible_controls(panel, phase, height):
    state = dict(phase=phase, current_version="1.2.1", version="1.2.2", available=phase not in {"idle", "checking", "latest"}, received=42, total=100, error="网络超时，请稍后重试。" if phase.endswith("_error") else "")
    panel.add_init_script(f"window.updateState={json.dumps(state)}")
    panel.set_viewport_size({"width": 311, "height": height})
    panel.goto("http://tokenbi.test/index.html")
    panel.locator("#settings-button").click()
    panel.locator("#update-action").scroll_into_view_if_needed()
    assert panel.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert panel.locator("footer").bounding_box()["y"] < height - 30
    assert panel.locator("#update-action").evaluate("e => e.scrollWidth <= e.clientWidth")
    assert panel.locator("#update-dot").is_visible() == state["available"]
    assert panel.locator('[data-action="pin"], #keep-open').count() == 0
    if phase in {"available", "ready", "download_error"} and height == 600:
        screenshot(panel, phase)


def test_hidden_panel_dismisses_stale_confirmation(panel):
    panel.clock.install()
    panel.goto("http://tokenbi.test/index.html")
    panel.locator('[data-action="quit"]').click()
    assert panel.locator("#confirm-dialog").is_visible()
    panel.evaluate("window.visible=false")
    panel.clock.run_for(2000)
    assert panel.locator("#confirm-dialog").is_hidden()
