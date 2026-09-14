"""Local-only interaction checks for the v1.2.1 HTML prototype, not the app."""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright


HERE = Path(__file__).resolve().parent
URL = (HERE.parent / "preview-v121-onboarding-updates.html").as_uri()


def verify(engine, name):
    browser = engine.launch()
    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    errors = []
    external = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: external.append(request.url) if request.url.startswith(("http:", "https:")) else None)
    page.goto(URL)
    expect(page.locator("#onboarding")).to_be_visible()
    expect(page.locator("#app-panel")).to_be_hidden()
    page.screenshot(path=str(HERE / f"{name}-first-launch.png"))
    page.locator("#open-from-tip").click()
    expect(page.locator("#home")).to_be_visible()
    assert page.locator("#app-panel").bounding_box()["width"] == 311
    page.reload()
    expect(page.locator("#onboarding")).to_be_hidden()
    page.locator("#scenario").select_option("available")
    expect(page.locator("#update-dot")).to_be_visible()
    page.locator("#app-panel").screenshot(path=str(HERE / f"{name}-home.png"))
    page.locator("#settings-button").click()
    expect(page.locator('#pin-toggle, [data-action="pin"], img[src$="/pin.svg"]')).to_have_count(0)
    expect(page.locator("#update-action")).to_have_text("立即更新")
    expect(page.locator("#update-dot")).to_be_visible()
    page.locator("#toggle-notes").click()
    expect(page.locator("#notes-list")).to_be_visible()
    page.screenshot(path=str(HERE / f"{name}-settings.png"))
    page.locator("#update-action").click()
    expect(page.locator("#update-action")).to_be_disabled()
    page.wait_for_timeout(450)
    page.locator("#app-panel").screenshot(path=str(HERE / f"{name}-downloading.png"))
    page.locator("#network").uncheck()
    expect(page.locator("#app-panel")).to_be_hidden()
    expect(page.locator("#update-title")).to_have_text("下载已中断")
    page.locator("#network").check()
    page.locator("#tray").click()
    page.locator("#update-action").click()
    page.locator("#update-later").click()
    expect(page.locator("#home")).to_be_visible()
    page.locator(".menu-context").click()
    expect(page.locator("#app-panel")).to_be_hidden()
    expect(page.locator("#tray")).to_have_attribute("aria-expanded", "false")
    page.wait_for_timeout(3900)
    expect(page.locator("#app-panel")).to_be_hidden()
    page.locator("#tray").click()
    page.locator("#settings-button").click()
    expect(page.locator("#update-action")).to_have_text("重启完成更新")
    expect(page.locator("#update-dot")).to_be_visible()
    page.locator("#app-panel").screenshot(path=str(HERE / f"{name}-ready.png"))
    page.locator("#update-later").click()
    page.locator("#settings-button").click()
    expect(page.locator("#update-action")).to_have_text("重启完成更新")
    page.locator("#update-action").click()
    expect(page.locator("#update-action")).to_be_disabled()
    expect(page.locator("#current-version")).to_have_text("1.2.2", timeout=4000)
    expect(page.locator("#update-dot")).to_be_hidden()
    page.locator("#app-panel").screenshot(path=str(HERE / f"{name}-success.png"))
    page.locator("#update-action").click()
    expect(page.locator("#update-title")).to_have_text("已是最新版本", timeout=4000)
    page.locator("#scenario").select_option("offline")
    page.locator("#update-action").click()
    expect(page.locator("#update-title")).to_have_text("暂时无法检查更新", timeout=4000)
    page.locator("#network").check()
    page.locator("#tray").click()
    page.locator("#update-action").click()
    expect(page.locator("#update-action")).to_have_text("立即更新", timeout=4000)
    page.locator("#scenario").select_option("verify-error")
    expect(page.locator("#update-title")).to_have_text("无法验证此更新")
    expect(page.locator("#update-action")).to_have_text("重新下载")
    expect(page.get_by_role("button", name="重启完成更新", exact=True)).to_have_count(0)
    page.locator("#app-panel").screenshot(path=str(HERE / f"{name}-verification-error.png"))

    # Starting another fixture cancels the previous async simulation.
    page.locator("#scenario").select_option("daily")
    page.locator("#settings-button").click()
    page.locator("#update-action").click()
    page.locator("#scenario").select_option("first")
    page.wait_for_timeout(1300)
    expect(page.locator("#onboarding")).to_be_visible()
    expect(page.locator("#update-dot")).to_be_hidden()
    page.locator("#ack-tip").click()
    page.locator("#tray").click()
    page.get_by_role("button", name="扫码连接副屏", exact=True).click()
    expect(page.locator("#qr")).to_be_visible()
    page.get_by_role("button", name="返回额度", exact=True).click()
    page.locator("#settings-button").click()
    page.get_by_role("button", name="诊断信息", exact=True).click()
    expect(page.locator("#diagnostics")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#app-panel")).to_be_hidden()

    # These browser event simulations cover dismissal wiring, not native macOS focus.
    page.locator("#scenario").select_option("daily")
    page.mouse.move(5, 5)
    expect(page.locator("#app-panel")).to_be_visible()
    page.locator("#settings-button").click()
    page.locator("#update-action").click()
    page.evaluate("window.dispatchEvent(new Event('blur'))")
    expect(page.locator("#app-panel")).to_be_hidden()
    page.wait_for_timeout(1300)
    expect(page.locator("#app-panel")).to_be_hidden()
    page.locator("#tray").click()
    expect(page.locator("#update-action")).to_have_text("立即更新")
    page.locator("#network").focus()
    expect(page.locator("#app-panel")).to_be_hidden()
    page.locator("#tray").click()
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable: true, value: true});
      try { document.dispatchEvent(new Event('visibilitychange')); }
      finally { delete document.hidden; }
    }""")
    expect(page.locator("#app-panel")).to_be_hidden()
    page.screenshot(path=str(HERE / f"{name}-dismissed.png"))
    page.locator("#tray").click()
    expect(page.locator("#settings")).to_be_visible()
    page.locator("#tray").click()
    expect(page.locator("#app-panel")).to_be_hidden()

    for width, height in [(1024, 768), (390, 844), (339, 800), (320, 700)]:
        page.set_viewport_size({"width": width, "height": height})
        page.locator("#scenario").select_option("available")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"page overflow at {width}"
        panel = page.locator("#app-panel").bounding_box()
        assert panel["x"] >= 0 and panel["x"] + panel["width"] <= width
        page.locator("#settings-button").click()
        page.locator("#toggle-notes").click()
        button = page.locator("#update-action").bounding_box()
        postpone = page.locator("#update-later").bounding_box()
        footer = page.locator(".panel footer").bounding_box()
        assert button["y"] + button["height"] < footer["y"], f"button/footer overlap at {width}"
        assert postpone["y"] + postpone["height"] < footer["y"], f"postpone/footer overlap at {width}"
        assert page.locator("#app-panel").evaluate("el => el.scrollWidth <= el.clientWidth")
        if width == 339:
            page.screenshot(path=str(HERE / f"{name}-339-settings.png"), full_page=True)
            page.locator("#scenario").select_option("first")
            page.screenshot(path=str(HERE / f"{name}-339-onboarding.png"), full_page=True)
    missing = page.locator("img").evaluate_all("images => images.filter(img => !img.complete || img.naturalWidth === 0).map(img => img.src)")
    assert not missing, missing
    assert not errors, errors
    assert not external, external
    print(f"{name}: passed; no pin controls, outside/focus/visibility dismissal, background updates, onboarding, retry, signature gate, navigation, 5 viewports; no page errors or HTTP requests")
    context.close()
    browser.close()


with sync_playwright() as playwright:
    verify(playwright.chromium, "chromium")
    verify(playwright.webkit, "webkit")
