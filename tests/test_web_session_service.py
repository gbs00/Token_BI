from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.source_errors import LiveSessionRequiredError
from app.services.web_session_service import NativeWebSession, WebSessionService
from app.services.usage_connectors import normalize_usage_payload
from test_wkwebview_probe import server  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ROOT / "dist/native/Token BI Web Session.app/Contents/MacOS/TokenBIWebSession"
NATIVE = pytest.mark.skipif(sys.platform != "darwin" or os.getenv("TOKEN_BI_NATIVE_WK_TEST") != "1",
                            reason="需显式开启 macOS 原生集成测试")
ALICE = hashlib.sha256(b"alice@example.test").hexdigest()


def test_status_never_launches_worker(test_settings):
    service = WebSessionService(test_settings)
    assert service.get_session_snapshot("account") is None
    assert not service.available()
    assert service._bridge is None
    assert not service._profile_path.exists()


def test_disconnect_preserves_only_profile_identifier(test_settings):
    service = WebSessionService(test_settings)
    profile = service._profile(create=True)
    assert service._profile_path.stat().st_mode & 0o777 == 0o600
    service.close_session()
    assert service._profile(create=False) == profile
    assert json.loads(service._profile_path.read_text()) == {"profile": profile}
    service.access_enabled = lambda: False
    with pytest.raises(LiveSessionRequiredError):
        service._get_bridge(login=True)
    assert service._bridge is None


def test_background_read_never_creates_login_profile(test_settings):
    service = WebSessionService(test_settings)
    with pytest.raises(LiveSessionRequiredError):
        service._profile(create=False)
    assert not service._profile_path.exists()


def test_shutdown_blocks_late_fallback(test_settings):
    service = WebSessionService(test_settings)
    service.shutdown()
    with pytest.raises(LiveSessionRequiredError):
        service._get_bridge(login=True)
    assert service._bridge is None


@NATIVE
@pytest.mark.parametrize("case,category", [
    ("cookie", "success"), ("bearer", "success"), ("empty-token", "success"),
    ("unauthorized", "auth_required"), ("limited", "rate_limited"),
    ("server-error", "network_error"), ("timeout", "timeout"),
    ("identity-changed", "identity_changed"), ("identity-missing", "identity_unknown"),
    ("dom", "success"), ("navigation-blocked", "navigation_blocked"),
    ("expired-session", "auth_required"), ("token-renewal", "success"),
    ("identity-check-offline", "network_error"), ("reset-error", "success"),
])
def test_production_worker_hidden_collection_and_shutdown(server, case, category):
    server.case = case
    worker = NativeWebSession(EXECUTABLE, None, lambda event: None,
                              fixture=f"http://127.0.0.1:{server.server_port}/fixture/{case}")
    try:
        assert worker.request("status")["visible"] is False
        result = worker.request("collect", ALICE)
        assert result["category"] == category, result
        assert worker.request("status")["visible"] is False
        if category == "success":
            assert result["identity"]["key"] == ALICE
            assert result["usage"]["rate_limit"]["secondary_window"]["used_percent"] == 18
        text = json.dumps(result)
        for secret in ["fixture-access-token", "alice@example.test", "session_secret_fixture",
                       "sensitive-credit-id", "secret-should-never-cross-native-bridge"]:
            assert secret not in text
        assert "authorization" not in result
        assert "dom" not in result
        if case in {"token-renewal", "unauthorized"}:
            assert server.usage_requests == 2
        if case == "expired-session":
            assert server.usage_requests == 0
        if case == "reset-error":
            credits = normalize_usage_payload(result["usage"], "web_session", "wkwebview_json")["reset_credits"]
            assert credits["available_count"] == 2
            assert credits["expires_at"] is None
        assert not server.unexpected
    finally:
        worker.close()


@NATIVE
def test_relogin_reuses_worker_then_close_retains_cookie(server):
    profile = str(uuid.uuid4())
    url = f"http://127.0.0.1:{server.server_port}/fixture/cookie"
    event = threading.Event()
    worker = NativeWebSession(EXECUTABLE, profile, lambda value: event.set() if value == "session_ready" else None, fixture=url)
    try:
        worker.request("login", ALICE)
        assert event.wait(10)
        pid = worker._process.pid
        event.clear()
        worker.request("login", ALICE)
        assert event.wait(10)
        assert worker._process.pid == pid
        worker.request("hide")
        assert worker.request("status")["visible"] is False
    finally:
        worker.close()
    server.case = "persist-read"
    worker = NativeWebSession(EXECUTABLE, profile, lambda value: None, fixture=url)
    try:
        assert worker.request("collect", ALICE)["category"] == "success"
    finally:
        worker.close()


@NATIVE
def test_disconnect_cancels_pending_pipe_request(server):
    server.case = "timeout"
    worker = NativeWebSession(EXECUTABLE, None, lambda value: None,
                              fixture=f"http://127.0.0.1:{server.server_port}/fixture/timeout")
    worker.request("status")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(worker.request, "collect", ALICE)
        worker.close()
        with pytest.raises(LiveSessionRequiredError):
            pending.result(timeout=5)
    assert not worker.alive
    assert not worker.alive
    assert worker._process.poll() is not None


@NATIVE
def test_worker_does_not_request_usage_for_other_account(server):
    worker = NativeWebSession(EXECUTABLE, None, lambda event: None,
                              fixture=f"http://127.0.0.1:{server.server_port}/fixture/cookie")
    try:
        result = worker.request("collect", "b" * 64)
        assert result["category"] == "account_mismatch"
        assert len(result["requests"]) == 1
        assert result.get("usage") is None
    finally:
        worker.close()
