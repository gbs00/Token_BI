from __future__ import annotations

import json
import base64
import subprocess
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime

import pytest

from app.models.account import AccountRecord, AccountStatus
from app.services.browser_worker_service import LiveSessionRequiredError
from app.services.scraper_service import (
    AnalyticsPageChangedError,
    ScraperUnavailableError,
    SessionExpiredError,
)
from app.services.usage_connectors import (
    CodexCliRpcConnector,
    CodexOAuthConnector,
    ConnectorChainError,
    ConnectorFailureCategory,
    ConnectorNetworkError,
    ConnectorNotApplicableError,
    ConnectorTimeoutError,
    LocalCodexConnector,
    UsageConnectorManager,
    UsageConnectorResult,
    WebSessionConnector,
)


class FailingConnector:
    name = "failing"
    source_type = "scraped"

    def fetch_usage(self, account):
        raise ScraperUnavailableError("connector failed")


class ReadyConnector:
    name = "ready"
    source_type = "scraped"

    def fetch_usage(self, account):
        return UsageConnectorResult(
            connector_name="ready",
            source_type="scraped",
            source_detail="network_response",
            payload={
                "session_remaining_pct": 90,
                "session_reset_at": "2026-04-22T03:00:00+08:00",
                "weekly_remaining_pct": 75,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
                "is_estimated": False,
            },
        )


class SensitiveFailingConnector:
    name = "sensitive_failing"
    source_type = "oauth"

    def fetch_usage(self, account):
        raise ScraperUnavailableError(
            "access_token=secret-token Authorization: Bearer another-token "
            "cookie=session-id someone.long@example.com"
        )


class TypedFailingConnector:
    source_type = "test"

    def __init__(self, name: str, error: ScraperUnavailableError) -> None:
        self.name = name
        self.error = error

    def fetch_usage(self, account):
        raise self.error


class FakeBrowserWorkerService:
    def fetch_usage(self, account):
        return {
            "session_remaining_pct": 88,
            "session_reset_at": "2026-04-22T03:00:00+08:00",
            "weekly_remaining_pct": 71,
            "weekly_reset_at": "2026-04-28T00:00:00+08:00",
            "updated_at": "2026-04-21T23:00:00+08:00",
            "source_detail": "network_response",
            "is_estimated": False,
        }


def _build_account(test_settings) -> AccountRecord:
    return AccountRecord(
        account_id="acc_local",
        account_alias="guo****@gmail.com",
        masked_email="guo****@gmail.com",
        status=AccountStatus.ACTIVE,
        session_storage_path=str(test_settings.runtime_contexts_dir / "acc_local"),
    )


def _build_unsigned_jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def encode(segment: dict) -> str:
        raw = json.dumps(segment, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode(header)}.{encode(payload)}.signature"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_rpc_partial_line_cannot_bypass_deadline(stream) -> None:
    connector = CodexCliRpcConnector(timeout_seconds=0.1)
    process = subprocess.Popen(
        [sys.executable, "-u", "-c",
         "import sys,time; sys." + stream + ".write('{\\\"id\\\":1'); sys." + stream
         + ".flush(); time.sleep(0.8); print(',\\\"result\\\":{}}')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True,
    )
    start = time.monotonic()
    try:
        with pytest.raises(ConnectorTimeoutError):
            connector._read_jsonrpc_response(process, request_id=1)
        assert time.monotonic() - start < 0.5
    finally:
        connector._stop_rpc_process(process)


def test_rpc_multiple_lines_in_one_read_are_not_lost() -> None:
    connector = CodexCliRpcConnector(timeout_seconds=0.5)
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", "print('{}\\n{\\\"id\\\":1,\\\"result\\\":{\\\"ok\\\":true}}')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert connector._read_jsonrpc_response(process, 1)["result"]["ok"] is True
    finally:
        connector._stop_rpc_process(process)


def test_cli_uses_one_process_for_identity_and_quota(test_settings, monkeypatch):
    from app.services import usage_connectors
    script = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'account/read':
        result = {'account': {'email': 'user@example.com'}}
    elif method == 'account/rateLimits/read':
        result = {'weekly_remaining_pct': 80}
    else:
        result = {}
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
"""
    popen = subprocess.Popen
    children = []
    def start_fake(_args, **kwargs):
        child = popen([sys.executable, "-u", "-c", script], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(usage_connectors.subprocess, "Popen", start_fake)
    monkeypatch.setattr(usage_connectors.shutil, "which", lambda _bin: "/synthetic/codex")
    result = CodexCliRpcConnector(timeout_seconds=1).fetch_usage(_build_account(test_settings))
    assert len(children) == 1
    assert children[0].poll() is not None
    assert result.payload["windows"][0]["remaining_pct"] == 80


def test_oauth_deadline_covers_slow_response_body(monkeypatch):
    release = threading.Event()
    class SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                while not release.is_set():
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    release.wait(0.01)
            except OSError:
                pass
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    try:
        start = time.monotonic()
        with pytest.raises(ConnectorTimeoutError):
            CodexOAuthConnector()._default_http_get(f"http://127.0.0.1:{server.server_port}", {}, 0.2)
        assert time.monotonic() - start < 0.8
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(1)


def test_oauth_identity_key_distinguishes_same_masked_emails(test_settings):
    keys = []
    for email in ("user.one@example.com", "user.two@example.com"):
        auth_path = test_settings.project_root / "test-auth.json"
        auth_path.write_text(json.dumps({"tokens": {
            "access_token": _build_unsigned_jwt({"email": email}),
        }}), encoding="utf-8")
        connector = CodexOAuthConnector(auth_paths=[auth_path], http_get=lambda *_: {
            "weekly_remaining_pct": 82,
        })
        payload = connector.fetch_usage(_build_account(test_settings)).payload
        assert payload["account_masked_email"] == "user****@example.com"
        assert email not in json.dumps(payload, default=str)
        keys.append(payload["account_identity_key"])
    assert keys[0] != keys[1]


def test_local_codex_connector_reads_snapshot(test_settings) -> None:
    account = _build_account(test_settings)
    snapshot = test_settings.runtime_local_connector_dir / f"{account.account_id}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "session_remaining_pct": 82,
                "session_reset_at": "2026-04-22T03:00:00+08:00",
                "weekly_remaining_pct": 67,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )

    result = LocalCodexConnector(test_settings.runtime_local_connector_dir).fetch_usage(account)

    assert result.connector_name == "local_codex"
    assert result.source_type == "local_snapshot"
    assert result.payload["windows"][0]["remaining_pct"] == 82


def test_local_codex_connector_accepts_weekly_only_snapshot(test_settings) -> None:
    account = _build_account(test_settings)
    snapshot = test_settings.runtime_local_connector_dir / f"{account.account_id}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "weekly_remaining_pct": 67,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )

    result = LocalCodexConnector(test_settings.runtime_local_connector_dir).fetch_usage(account)

    assert result.connector_name == "local_codex"
    assert [window["display_name"] for window in result.payload["windows"]] == ["Weekly"]
    assert result.payload["windows"][0]["remaining_pct"] == 67


def test_local_codex_connector_skips_when_snapshot_missing(test_settings) -> None:
    account = _build_account(test_settings)
    connector = LocalCodexConnector(test_settings.runtime_local_connector_dir)

    with pytest.raises(ConnectorNotApplicableError):
        connector.fetch_usage(account)


def test_connector_manager_falls_back_after_failure(test_settings) -> None:
    account = _build_account(test_settings)
    manager = UsageConnectorManager([FailingConnector(), ReadyConnector()])

    result = manager.fetch_usage(account)

    assert result.connector_name == "ready"
    assert result.source_detail == "network_response"


def test_connector_manager_redacts_sensitive_error_details(test_settings) -> None:
    account = _build_account(test_settings)
    manager = UsageConnectorManager([SensitiveFailingConnector()])

    with pytest.raises(ScraperUnavailableError):
        manager.fetch_usage(account)

    message = manager.last_connector_errors[0]["message"]
    assert "secret-token" not in message
    assert "another-token" not in message
    assert "session-id" not in message
    assert "someone.long@example.com" not in message
    assert "some****@example.com" in message


def test_primary_transient_error_is_not_overwritten_by_missing_web_session(test_settings) -> None:
    account = _build_account(test_settings)
    manager = UsageConnectorManager(
        [
            TypedFailingConnector("codex_oauth", ConnectorNetworkError("OAuth network failed")),
            TypedFailingConnector("codex_cli_rpc", ConnectorTimeoutError("CLI timed out")),
            TypedFailingConnector(
                "browser_worker",
                LiveSessionRequiredError("No live browser worker for this account."),
            ),
        ]
    )

    with pytest.raises(ConnectorChainError) as captured:
        manager.fetch_usage(account)

    assert captured.value.category == ConnectorFailureCategory.TIMEOUT
    assert captured.value.category != ConnectorFailureCategory.WEB_SESSION_INACTIVE
    assert manager.last_connector_errors[-1]["category"] == "web_session_inactive"


def test_definitive_primary_auth_failure_wins_over_web_fallback_state(test_settings) -> None:
    account = _build_account(test_settings)
    manager = UsageConnectorManager(
        [
            TypedFailingConnector("codex_oauth", SessionExpiredError("OAuth expired")),
            TypedFailingConnector("codex_cli_rpc", SessionExpiredError("CLI signed out")),
            TypedFailingConnector(
                "browser_worker",
                LiveSessionRequiredError("No live browser worker for this account."),
            ),
        ]
    )

    with pytest.raises(ConnectorChainError) as captured:
        manager.fetch_usage(account)

    assert captured.value.category == ConnectorFailureCategory.AUTH_REQUIRED


def test_oauth_connector_reads_codex_auth_and_normalizes_official_windows(test_settings) -> None:
    account = _build_account(test_settings)
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": "secret-token"}}),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_http_get(url: str, headers: dict[str, str], timeout: float) -> dict:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 20,
                    "reset_at": "2026-05-23T18:00:00+08:00",
                    "limit_window_seconds": 18000,
                }
            }
        }

    connector = CodexOAuthConnector(
        auth_paths=[auth_path],
        usage_url="https://chatgpt.com/backend-api/wham/usage",
        http_get=fake_http_get,
        timeout_seconds=2.0,
    )

    result = connector.fetch_usage(account)

    assert result.connector_name == "codex_oauth"
    assert result.source_type == "oauth"
    assert result.source_detail == "oauth_usage_api"
    assert result.payload["windows"][0]["display_name"] == "5h window"
    assert result.payload["windows"][0]["remaining_pct"] == 80
    assert isinstance(result.payload["windows"][0]["reset_at"], datetime)
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in json.dumps(result.payload, default=str)


def test_oauth_connector_syncs_masked_identity_from_codex_profile_claim(test_settings) -> None:
    account = _build_account(test_settings)
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": _build_unsigned_jwt(
                        {
                            "exp": 4102444800,
                            "https://api.openai.com/profile": {
                                "email": "someone.long@example.com",
                                "email_verified": True,
                            },
                        }
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    connector = CodexOAuthConnector(
        auth_paths=[auth_path],
        usage_url="https://chatgpt.com/backend-api/wham/usage",
        http_get=lambda *_args, **_kwargs: {
            "rate_limit": {
                "primary_window": {
                    "remaining_pct": 73,
                    "reset_at": "2026-05-23T18:00:00+08:00",
                    "limit_window_seconds": 18000,
                }
            }
        },
        timeout_seconds=2.0,
    )

    result = connector.fetch_usage(account)

    assert result.payload["account_masked_email"] == "some****@example.com"


def test_oauth_connector_prefers_id_token_identity(test_settings) -> None:
    account = _build_account(test_settings)
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": _build_unsigned_jwt({"exp": 4102444800}),
                    "id_token": _build_unsigned_jwt(
                        {
                            "exp": 4102444800,
                            "email": "current.codex@example.com",
                        }
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    connector = CodexOAuthConnector(
        auth_paths=[auth_path],
        http_get=lambda *_args, **_kwargs: {
            "rate_limit": {
                "primary_window": {
                    "remaining_pct": 73,
                    "reset_at": "2026-05-23T18:00:00+08:00",
                    "limit_window_seconds": 18000,
                }
            }
        },
    )

    result = connector.fetch_usage(account)

    assert result.payload["account_masked_email"] == "curr****@example.com"


def test_oauth_connector_reports_expired_auth_as_unavailable(test_settings) -> None:
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": _build_unsigned_jwt({"exp": 1}),
                }
            }
        ),
        encoding="utf-8",
    )
    connector = CodexOAuthConnector(auth_paths=[auth_path])

    assert connector.auth_available() is False


def test_oauth_connector_skips_when_auth_file_missing(test_settings) -> None:
    account = _build_account(test_settings)
    connector = CodexOAuthConnector(
        auth_paths=[test_settings.config_dir / "missing-auth.json"],
        usage_url="https://chatgpt.com/backend-api/wham/usage",
        http_get=lambda *_args, **_kwargs: {},
        timeout_seconds=2.0,
    )

    with pytest.raises(ConnectorNotApplicableError):
        connector.fetch_usage(account)


def test_oauth_connector_uses_next_auth_path_when_first_is_unreadable(test_settings) -> None:
    account = _build_account(test_settings)
    broken_path = test_settings.config_dir / "broken-auth.json"
    valid_path = test_settings.config_dir / "valid-auth.json"
    broken_path.write_text("{", encoding="utf-8")
    valid_path.write_text(
        json.dumps({"tokens": {"access_token": "valid-token"}}),
        encoding="utf-8",
    )
    connector = CodexOAuthConnector(
        auth_paths=[broken_path, valid_path],
        http_get=lambda *_args, **_kwargs: {
            "rate_limit": {
                "primary_window": {
                    "remaining_pct": 80,
                    "reset_at": "2026-05-23T18:00:00+08:00",
                    "limit_window_seconds": 18000,
                }
            }
        },
    )

    result = connector.fetch_usage(account)

    assert result.payload["windows"][0]["remaining_pct"] == 80


def test_malformed_official_reset_time_becomes_source_change(test_settings) -> None:
    account = _build_account(test_settings)
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps({"tokens": {"access_token": "valid-token"}}),
        encoding="utf-8",
    )
    connector = CodexOAuthConnector(
        auth_paths=[auth_path],
        http_get=lambda *_args, **_kwargs: {
            "rate_limit": {
                "primary_window": {
                    "remaining_pct": 80,
                    "reset_at": "not-a-date",
                    "limit_window_seconds": 18000,
                }
            }
        },
    )

    with pytest.raises(AnalyticsPageChangedError):
        connector.fetch_usage(account)


def test_cli_rpc_connector_reads_account_and_rate_limit_windows(test_settings) -> None:
    account = _build_account(test_settings)
    seen_methods: list[str] = []

    def fake_rpc(method: str, params):
        seen_methods.append(method)
        if method == "account/read":
            return {
                "account": {
                    "type": "chatgpt",
                    "email": "someone.long@example.com",
                    "planType": "pro",
                },
                "requiresOpenaiAuth": False,
            }
        if method == "account/rateLimits/read":
            return {
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitId": "codex",
                        "limitName": "Codex",
                        "primary": {
                            "usedPercent": 12,
                            "resetsAt": 1776843664,
                            "windowDurationMins": 300,
                        },
                        "secondary": {
                            "usedPercent": 4,
                            "resetsAt": 1777430464,
                            "windowDurationMins": 10080,
                        },
                    }
                },
                "rateLimits": None,
            }
        raise AssertionError(method)

    connector = CodexCliRpcConnector(
        codex_bin="codex",
        rpc_client=fake_rpc,
        timeout_seconds=2.0,
    )

    result = connector.fetch_usage(account)

    assert seen_methods == ["account/read", "account/rateLimits/read", "account/read"]
    assert result.connector_name == "codex_cli_rpc"
    assert result.source_type == "cli_rpc"
    assert result.payload["account_masked_email"] == "some****@example.com"
    assert [window["remaining_pct"] for window in result.payload["windows"]] == [88, 96]
    assert [window["window_minutes"] for window in result.payload["windows"]] == [300, 10080]


def test_web_session_connector_uses_browser_worker(test_settings) -> None:
    account = _build_account(test_settings)
    connector = WebSessionConnector(FakeBrowserWorkerService())

    result = connector.fetch_usage(account)

    assert result.connector_name == "browser_worker"
    assert result.source_detail == "network_response"
    assert result.source_type == "web_session"
    assert result.payload["windows"][0]["remaining_pct"] == 88


def test_cli_rejects_account_change_during_quota_read(test_settings):
    emails = iter(["first@example.com", "second@example.com"])
    def rpc(method, _params):
        if method == "account/read":
            return {"account": {"email": next(emails)}}
        return {"weekly_remaining_pct": 10}
    connector = CodexCliRpcConnector(rpc_client=rpc)
    with pytest.raises(ConnectorNetworkError, match="账号在采集期间发生变化"):
        connector.fetch_usage(_build_account(test_settings))
