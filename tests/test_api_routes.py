from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models.account import AccountRecord, AccountStatus
from app.models.browser_session import BrowserSessionSnapshot, BrowserSessionState
from app.services.usage_connectors import UsageConnectorResult


def local_client(app):
    return TestClient(app, client=("127.0.0.1", 54321), base_url="http://127.0.0.1")


@pytest.mark.parametrize("host", ["192.0.2.10", "::ffff:192.0.2.10", "2001:db8::10"])
@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/accounts"), ("GET", "/api/v1/accounts"),
    ("POST", "/api/v1/account-session/logout"), ("POST", "/api/v1/account-session/login"),
    ("POST", "/api/v1/accounts/acc_missing/reauth"),
    ("GET", "/api/v1/accounts/acc_missing/session"),
    ("GET", "/api/v1/diagnostics"), ("GET", "/api/v1/runtime-status"),
])
def test_lan_cannot_manage_accounts(app, host, method, path, monkeypatch) -> None:
    def no_browser(*_args, **_kwargs):
        raise AssertionError("越权请求不应进入浏览器操作")
    monkeypatch.setattr(app.state.container.browser_worker_service, "start_login_session", no_browser)
    client = TestClient(app, client=(host, 54321))
    response = client.request(method, path, json={})
    assert response.status_code == 403
    assert app.state.container.account_service.list_accounts() == []


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_loopback_management_includes_ipv4_mapped_ipv6(app, host) -> None:
    response = TestClient(app, client=(host, 54321), base_url="http://localhost").get("/api/v1/accounts")
    assert response.status_code == 200


def test_external_origin_cannot_logout_via_loopback(app) -> None:
    response = local_client(app).post("/api/v1/account-session/logout", headers={"Origin": "https://untrusted.example"})
    assert response.status_code == 403


def test_lan_dashboard_remains_readable_and_refreshable_without_private_paths(app) -> None:
    account_id = _create_account_with_context(app)
    client = TestClient(app, client=("::ffff:192.0.2.10", 54321))
    response = client.post("/api/v1/dashboard/refresh")
    assert response.status_code == 200
    assert response.json()["state"] == "ready"
    for payload in (response.json(), client.get("/api/v1/dashboard").json()):
        assert payload["account"]["account_id"] == account_id
        assert "session_storage_path" not in json.dumps(payload)
        assert "identity_key" not in json.dumps(payload)


def _create_account_with_context(app):
    container = app.state.container
    response = local_client(app).post(
        "/api/v1/accounts",
        json={"masked_email": "guo****@gmail.com"},
    )
    account = response.json()["account"]
    account_id = account["account_id"]
    context_dir = container.session_service.ensure_context_dir(account_id)
    (context_dir / "state.json").write_text("ok", encoding="utf-8")
    snapshot_path = container.settings.runtime_local_connector_dir / f"{account_id}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "session_remaining_pct": 86,
                "session_reset_at": "2026-04-22T03:00:00+08:00",
                "weekly_remaining_pct": 72,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    return account_id


def test_create_and_list_accounts_api(app) -> None:
    client = local_client(app)
    response = client.post(
        "/api/v1/accounts",
        json={"masked_email": "guo****@gmail.com"},
    )
    assert response.status_code == 201

    listing = client.get("/api/v1/accounts")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["account_alias"] == "guo****@gmail.com"


def test_main_health_identifies_service_and_process(app) -> None:
    response = local_client(app).get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "token-bi-main-service"
    assert payload["pid"] > 0
    assert payload["port"] == 8787


def test_create_account_without_masked_email_uses_pending_placeholder(app) -> None:
    client = local_client(app)
    response = client.post("/api/v1/accounts", json={})

    assert response.status_code == 201
    account = response.json()["account"]
    assert account["account_id"].startswith("acc_")
    assert account["masked_email"].startswith("Signing in ")
    assert account["account_alias"] == account["masked_email"]
    assert account["status"] == "pending"


def test_dashboard_api_returns_empty_state(app) -> None:
    client = local_client(app)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert response.json()["state"] == "empty"


def test_validate_account_uses_refresh_flow(app) -> None:
    client = local_client(app)
    account_id = _create_account_with_context(app)

    response = client.post(f"/api/v1/accounts/{account_id}/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["validated"] is True
    assert payload["dashboard_state"] == "ready"
    assert payload["account"]["status"] == "active"


def test_validate_account_syncs_detected_masked_identity(app) -> None:
    client = local_client(app)
    account = client.post("/api/v1/accounts", json={}).json()["account"]
    account_id = account["account_id"]
    snapshot_path = app.state.container.settings.runtime_local_connector_dir / f"{account_id}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "account_masked_email": "user****@example.com",
                "session_remaining_pct": 86,
                "session_reset_at": "2026-04-22T03:00:00+08:00",
                "weekly_remaining_pct": 72,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )

    response = client.post(f"/api/v1/accounts/{account_id}/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["validated"] is True
    assert payload["account"]["masked_email"] == "user****@example.com"
    assert payload["account"]["account_alias"] == "user****@example.com"


def test_refresh_dashboard_endpoint_returns_live_payload(app) -> None:
    client = local_client(app)
    account_id = _create_account_with_context(app)
    minimized: list[str] = []
    app.state.container.browser_worker_service.minimize_session = lambda account_id: minimized.append(account_id) or True

    response = client.post(f"/api/v1/dashboard/refresh?account_id={account_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "ready"
    assert payload["account"]["status"] == "active"
    assert payload["summary"]["source_type"] == "local_snapshot"
    assert payload["summary"]["source_detail"] == "local_snapshot_json"
    assert minimized == []


def test_account_session_login_creates_pending_account_and_opens_worker(app) -> None:
    client = local_client(app)
    captured = {}

    def fake_start_login_session(account_id: str, context_dir, target_url=None):
        captured["account_id"] = account_id
        captured["context_dir"] = str(context_dir)
        captured["target_url"] = target_url
        return BrowserSessionSnapshot(
            account_id=account_id,
            state=BrowserSessionState.AWAITING_LOGIN,
            context_dir=str(context_dir),
            current_url="https://chatgpt.com/#usage",
        )

    app.state.container.browser_worker_service.start_login_session = fake_start_login_session

    response = client.post("/api/v1/account-session/login")

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "login"
    assert payload["account"]["status"] == "pending"
    assert payload["session"]["state"] == "awaiting_login"
    assert captured["account_id"] == payload["account"]["account_id"]


def test_account_session_login_reuses_single_existing_account(app) -> None:
    client = local_client(app)
    existing = client.post(
        "/api/v1/accounts",
        json={"masked_email": "user****@example.com"},
    ).json()["account"]
    app.state.container.account_service.update_account_status(existing["account_id"], "active")

    app.state.container.browser_worker_service.start_login_session = (
        lambda account_id, context_dir, target_url=None: BrowserSessionSnapshot(
            account_id=account_id,
            state=BrowserSessionState.AWAITING_LOGIN,
            context_dir=str(context_dir),
        )
    )

    response = client.post("/api/v1/account-session/login")

    assert response.status_code == 200
    assert response.json()["account"]["account_id"] == existing["account_id"]
    assert len(app.state.container.account_service.list_accounts()) == 1


def test_account_session_logout_closes_worker_deletes_account_and_profile(app) -> None:
    client = local_client(app)
    account = client.post(
        "/api/v1/accounts",
        json={"masked_email": "user****@example.com"},
    ).json()["account"]
    account_id = account["account_id"]
    context_dir = app.state.container.session_service.ensure_context_dir(account_id)
    marker = context_dir / "Default" / "Cookies"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("cookie", encoding="utf-8")
    closed: list[str] = []
    app.state.container.browser_worker_service.close_session = lambda account_id: closed.append(account_id)

    response = client.post(f"/api/v1/account-session/logout?account_id={account_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "logout"
    assert payload["account_id"] == account_id
    assert payload["next_button_label"] == "登录账号"
    assert closed == [account_id]
    assert app.state.container.account_service.get_account(account_id) is None
    assert context_dir.exists() is False
    assert app.state.container.account_service.access_state()[0] is False
    assert client.post("/api/v1/dashboard/refresh").json()["metrics"] == []


def test_login_after_logout_reuses_oauth_without_opening_chrome(app, monkeypatch):
    container = app.state.container
    class OAuth:
        name = "codex_oauth"
        calls = 0
        def auth_available(self):
            return True
        def fetch_usage(self, _account):
            self.calls += 1
            return UsageConnectorResult("codex_oauth", "oauth", "oauth_usage_api", {
                "account_masked_email": "user****@example.com",
                "windows": [{"metric_type": "weekly", "remaining_pct": 80}],
            })
    oauth = OAuth()
    monkeypatch.setattr(container.usage_connector_manager, "_connectors", [oauth])
    def no_browser(*_args, **_kwargs):
        raise AssertionError("存在 OAuth 时不应打开浏览器")
    monkeypatch.setattr(container.browser_worker_service, "start_login_session", no_browser)
    auth = container.settings.codex_auth_paths[0]
    auth.write_text("synthetic credentials, do not modify", encoding="utf-8")
    client = local_client(app)
    client.post("/api/v1/account-session/logout")
    assert client.post("/api/v1/dashboard/refresh").json()["state"] == "empty"
    assert oauth.calls == 0
    result = client.post("/api/v1/account-session/login").json()
    assert result["ok"] is True
    assert result["action"] == "resume"
    assert result["session"] is None
    assert oauth.calls == 1
    assert auth.read_text(encoding="utf-8") == "synthetic credentials, do not modify"


def test_loopback_host_cannot_be_rebound_by_external_site(app):
    response = local_client(app).get("/api/v1/accounts", headers={"Host": "untrusted.example"})
    assert response.status_code == 403


def test_diagnostics_returns_actionable_copy_for_common_states(app) -> None:
    client = local_client(app)

    response = client.get("/api/v1/diagnostics")

    assert response.status_code == 200
    payload = response.json()
    codes = {item["code"] for item in payload["items"]}
    assert "service_ready" in codes
    assert "chrome_available" in codes
    assert "codex_auth_available" in codes
    assert "codex_cli_available" in codes
    assert "oauth_connector_ready" in codes
    assert "cli_rpc_connector_ready" in codes
    assert "web_session_available" in codes
    assert "last_connector_error" in codes
    assert all(item["title"] and item["next_step"] for item in payload["items"])
    by_code = {item["code"]: item for item in payload["items"]}
    assert by_code["oauth_connector_ready"]["severity"] == "warning"
    assert by_code["cli_rpc_connector_ready"]["severity"] == "warning"


def test_runtime_status_reports_only_last_successful_usage(app) -> None:
    client = local_client(app)
    account_id = _create_account_with_context(app)

    before = client.get("/api/v1/runtime-status").json()
    assert before["service"] == "token-bi-main-service"
    assert before["usage"]["state"] == "empty"
    assert before["usage"]["has_data"] is False

    client.post(f"/api/v1/dashboard/refresh?account_id={account_id}")
    after = client.get("/api/v1/runtime-status").json()

    assert after["account"]["account_id"] == account_id
    assert after["usage"]["state"] == "ready"
    assert after["usage"]["source_type"] == "local_snapshot"
    assert after["usage"]["updated_at"] is not None
    assert after["usage"]["source_updated_at"] == "2026-04-21T23:00:00+08:00"
    assert after["usage"]["next_sync_at"] is not None


def test_service_startup_does_not_launch_browser_worker_for_active_accounts(container) -> None:
    now = datetime.now(timezone.utc)
    container.account_service._write_accounts(
        [
            AccountRecord(
                account_id="acc_real_active",
                account_alias="user****@example.com",
                masked_email="user****@example.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_real_active",
                created_at=now,
                last_validated_at=now,
            )
        ]
    )
    launched: list[str] = []
    container.browser_worker_service.ensure_worker_for_account = lambda account, target_url=None: launched.append(
        account.account_id
    )

    container.startup()

    assert launched == []


def test_connector_order_prioritizes_oauth_and_cli_before_web_session(container) -> None:
    connector_names = [connector.name for connector in container.usage_connector_manager.connectors]

    assert connector_names[:2] == ["codex_oauth", "codex_cli_rpc"]
    assert connector_names[-1] == "browser_worker"


def test_reauth_endpoint_starts_live_browser_worker(app) -> None:
    client = local_client(app)
    account = client.post(
        "/api/v1/accounts",
        json={"masked_email": "guo****@gmail.com"},
    ).json()["account"]
    account_id = account["account_id"]
    captured = {}

    def fake_start_login_session(account_id: str, context_dir, target_url=None):
        captured["account_id"] = account_id
        captured["context_dir"] = str(context_dir)
        captured["target_url"] = target_url
        return BrowserSessionSnapshot(
            account_id=account_id,
            state=BrowserSessionState.AWAITING_LOGIN,
            context_dir=str(context_dir),
            current_url="https://chatgpt.com/#usage",
        )

    app.state.container.browser_worker_service.start_login_session = fake_start_login_session

    response = client.post(f"/api/v1/accounts/{account_id}/reauth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account_id"] == account_id
    assert payload["session"]["state"] == "awaiting_login"
    assert captured["account_id"] == account_id
    assert captured["target_url"] is None


def test_get_account_session_returns_worker_snapshot(app) -> None:
    client = local_client(app)
    account = client.post(
        "/api/v1/accounts",
        json={"masked_email": "guo****@gmail.com"},
    ).json()["account"]
    account_id = account["account_id"]

    app.state.container.browser_worker_service.restore_session_snapshot = (
        lambda _: BrowserSessionSnapshot(
            account_id=account_id,
            state=BrowserSessionState.READY,
            context_dir=f"/tmp/{account_id}",
            current_url="https://chatgpt.com/codex/cloud/settings/analytics#usage",
        )
    )

    response = client.get(f"/api/v1/accounts/{account_id}/session")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session"]["state"] == "ready"
    assert payload["session"]["current_url"].endswith("#usage")


def test_dashboard_api_maps_demo_query_to_real_visible_account(app) -> None:
    client = local_client(app)
    now = datetime.now(timezone.utc)
    app.state.container.account_service._write_accounts(
        [
            AccountRecord(
                account_id="acc_demo_main",
                account_alias="demo",
                masked_email="user****@example.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_demo_main",
                created_at=now,
            ),
            AccountRecord(
                account_id="acc_real_active",
                account_alias="user****@example.com",
                masked_email="user****@example.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_real_active",
                created_at=now,
                last_validated_at=now,
            ),
        ]
    )
    snapshot_path = app.state.container.settings.runtime_local_connector_dir / "acc_real_active.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "session_remaining_pct": 85,
                "session_reset_at": "2026-04-22T15:41:04+08:00",
                "weekly_remaining_pct": 98,
                "weekly_reset_at": "2026-04-29T10:41:04+08:00",
                "updated_at": "2026-04-22T14:54:44+08:00",
            }
        ),
        encoding="utf-8",
    )

    app.state.container.usage_sync_coordinator.refresh("acc_real_active")

    response = client.get("/api/v1/dashboard?account_id=acc_demo_main")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"]["account_id"] == "acc_real_active"
    assert payload["metrics"][0]["remaining_pct"] == 85
