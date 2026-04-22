from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models.account import AccountRecord, AccountStatus
from app.models.browser_session import BrowserSessionSnapshot, BrowserSessionState


def _create_account_with_context(app):
    container = app.state.container
    response = TestClient(app).post(
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
    client = TestClient(app)
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


def test_dashboard_api_returns_empty_state(app) -> None:
    client = TestClient(app)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert response.json()["state"] == "empty"


def test_validate_account_uses_refresh_flow(app) -> None:
    client = TestClient(app)
    account_id = _create_account_with_context(app)

    response = client.post(f"/api/v1/accounts/{account_id}/validate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["validated"] is True
    assert payload["dashboard_state"] == "ready"
    assert payload["account"]["status"] == "active"


def test_refresh_dashboard_endpoint_returns_live_payload(app) -> None:
    client = TestClient(app)
    account_id = _create_account_with_context(app)

    response = client.post(f"/api/v1/dashboard/refresh?account_id={account_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "ready"
    assert payload["account"]["status"] == "active"
    assert payload["summary"]["source_type"] == "local_snapshot"
    assert payload["summary"]["source_detail"] == "local_snapshot_json"


def test_reauth_endpoint_starts_live_browser_worker(app) -> None:
    client = TestClient(app)
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
    client = TestClient(app)
    account = client.post(
        "/api/v1/accounts",
        json={"masked_email": "guo****@gmail.com"},
    ).json()["account"]
    account_id = account["account_id"]

    app.state.container.browser_worker_service.get_session_snapshot = (
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
    client = TestClient(app)
    now = datetime.now(timezone.utc)
    app.state.container.account_service._write_accounts(
        [
            AccountRecord(
                account_id="acc_demo_main",
                account_alias="demo",
                masked_email="8754****@qq.com",
                status=AccountStatus.ACTIVE,
                session_storage_path="/tmp/acc_demo_main",
                created_at=now,
            ),
            AccountRecord(
                account_id="acc_real_active",
                account_alias="8754****@qq.com",
                masked_email="8754****@qq.com",
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

    response = client.get("/api/v1/dashboard?account_id=acc_demo_main")

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"]["account_id"] == "acc_real_active"
    assert payload["metrics"][0]["remaining_pct"] == 85
