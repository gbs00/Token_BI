from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def page(app):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        if not Path(runtime.chromium.executable_path).exists():
            pytest.skip("本地 Chromium 未安装，需单独执行浏览器回归")
        browser = runtime.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 568, "height": 320})
        client = TestClient(app, base_url="http://tokenbi.test")
        page.set_default_timeout(5000)
        def serve(route):
            if urlsplit(route.request.url).hostname != "tokenbi.test":
                route.abort()
                return
            path = urlsplit(route.request.url).path
            response = client.get(path)
            route.fulfill(body=response.content, status=response.status_code,
                          content_type=response.headers.get("content-type", "text/plain"))
        page.route("**/*", serve)
        page.clock.install()
        yield page
        browser.close()


def dashboard_payload(state="ready"):
    return {
        "account": {"account_id": "acc_test", "masked_email": "user****@example.com"},
        "state": state, "message": None if state == "ready" else "额度接口暂时不可用",
        "summary": {"source_type": "oauth", "last_success_at": "2026-09-05T03:00:00Z"},
        "metrics": [{"metric_type": "weekly", "remaining_pct": 82}],
    }


@pytest.mark.parametrize("abort_available", [True, False])
def test_hanging_dashboard_request_times_out_and_recovers(page, abort_available):
    page.add_init_script("""
        window.calls = 0;
        %s
        window.fetch = () => {
            window.calls++;
            if (window.calls === 1) return new Promise(() => {});
            return Promise.resolve(new Response(JSON.stringify(%s)));
        };
    """ % ("" if abort_available else "window.AbortController = undefined;", json.dumps(dashboard_payload())))
    page.goto("http://tokenbi.test/dashboard")
    page.clock.run_for(9000)
    assert "连接中断" in page.locator("[data-message-banner]").inner_text()
    page.clock.run_for(16000)
    assert page.evaluate("window.calls") >= 2
    assert page.locator("[data-metric-percent]").inner_text() == "82%"


@pytest.mark.parametrize("state", ["stale", "reauth_required", "rate_limited", "source_changed", "error", "empty"])
def test_failed_sync_http_200_never_shows_success_toast(page, state):
    page.add_init_script("window.fetch = () => Promise.resolve(new Response(JSON.stringify(%s)));"
                         % json.dumps(dashboard_payload(state)))
    page.goto("http://tokenbi.test/dashboard")
    page.locator("[data-refresh-link]").click()
    page.wait_for_function("document.querySelector('[data-toast]').classList.contains('show')")
    assert "额度已同步" not in page.locator("[data-toast]").inner_text()
    assert "danger" in page.locator("[data-toast]").get_attribute("class")
    assert page.locator("[data-refresh-link]").is_enabled()


def test_manual_sync_discards_older_poll_response(page):
    older, newer = dashboard_payload(), dashboard_payload()
    newer["metrics"][0]["remaining_pct"] = 51
    page.add_init_script("""
        window.fetch = (url, options) => options.method === 'POST'
            ? Promise.resolve(new Response(JSON.stringify(%s)))
            : new Promise(resolve => { window.finishOld = () => resolve(new Response(JSON.stringify(%s))); });
    """ % (json.dumps(newer), json.dumps(older)))
    page.goto("http://tokenbi.test/dashboard")
    page.locator("[data-refresh-link]").click()
    page.wait_for_function("document.querySelector('[data-metric-percent]')?.textContent === '51%'")
    page.evaluate("window.finishOld()")
    assert page.locator("[data-metric-percent]").inner_text() == "51%"
