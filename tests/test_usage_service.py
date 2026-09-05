from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.account import AccountStatus, CreateAccountRequest
from app.models.usage_snapshot import PageState
from app.services.scraper_service import AnalyticsPageChangedError, SessionExpiredError
from app.services.usage_connectors import UsageConnectorResult
from app.services.usage_service import UsageService


class FakeConnectorManager:
    def __init__(self, mode: str = "ready") -> None:
        self.mode = mode
        self.calls = 0

    def fetch_usage(self, account):
        self.calls += 1
        now = datetime.now(timezone.utc)
        if self.mode == "expired":
            raise SessionExpiredError("Codex login expired.")
        if self.mode == "unknown_window":
            windows = [
                {
                    "display_name": "Unknown window",
                    "remaining_pct": 58,
                    "reset_at": now + timedelta(hours=7),
                    "window_minutes": 420,
                }
            ]
        elif self.mode == "weekly_only":
            windows = [
                {
                    "display_name": "Weekly",
                    "remaining_pct": 89,
                    "reset_at": now + timedelta(days=5),
                    "window_minutes": 10080,
                }
            ]
        else:
            windows = [
                {
                    "display_name": "5h window",
                    "remaining_pct": 84,
                    "reset_at": now + timedelta(hours=3),
                    "window_minutes": 300,
                },
                {
                    "display_name": "Weekly",
                    "remaining_pct": 61,
                    "reset_at": now + timedelta(days=4),
                    "window_minutes": 10080,
                },
            ]
        if self.mode == "sensitive_raw_window":
            windows[0]["raw_window"] = {"access_token": "secret-token"}
        source_type = "local_snapshot" if self.mode == "local" else "oauth"
        source_detail = "local_snapshot_json" if self.mode == "local" else "oauth_usage_api"
        return UsageConnectorResult(
            connector_name="local_codex" if self.mode == "local" else "codex_oauth",
            source_type=source_type,
            source_detail=source_detail,
            payload={
                "account_masked_email": "user****@example.com",
                "updated_at": now,
                "is_estimated": False,
                "windows": windows,
            },
        )


def _make_service(container, mode: str = "ready") -> tuple[UsageService, FakeConnectorManager]:
    connector_manager = FakeConnectorManager(mode=mode)
    return (
        UsageService(
            account_service=container.account_service,
            session_service=container.session_service,
            connector_manager=connector_manager,
        ),
        connector_manager,
    )


def _make_account(container, status: AccountStatus = AccountStatus.ACTIVE):
    account = container.account_service.create_account(
        CreateAccountRequest(masked_email="old****@example.com")
    )
    return container.account_service.update_account_status(account.account_id, status.value)


def test_empty_dashboard_does_not_call_upstream_when_no_accounts(container) -> None:
    payload = container.usage_service.empty_dashboard()

    assert payload.state == PageState.EMPTY
    assert payload.account is None
    assert payload.metrics == []


def test_sync_bootstraps_local_codex_account_when_no_records(container) -> None:
    service, manager = _make_service(container)

    payload = service.sync_dashboard()

    assert manager.calls == 1
    assert payload.state == PageState.READY
    assert payload.account is not None
    assert payload.account.status == AccountStatus.ACTIVE
    assert payload.account.masked_email == "user****@example.com"
    assert len(container.account_service.list_accounts()) == 1


@pytest.mark.parametrize("initial_status", [AccountStatus.PENDING, AccountStatus.INVALID, AccountStatus.EXPIRED])
def test_account_status_never_blocks_oauth_or_cli_sync(container, initial_status) -> None:
    account = _make_account(container, initial_status)
    service, manager = _make_service(container)

    payload = service.sync_dashboard(account.account_id)

    assert manager.calls == 1
    assert payload.state == PageState.READY
    assert payload.account is not None
    assert payload.account.status == AccountStatus.ACTIVE
    assert payload.account.masked_email == "user****@example.com"


def test_sync_uses_actual_connector_metadata(container) -> None:
    account = _make_account(container)
    service, _ = _make_service(container, mode="local")

    payload = service.sync_dashboard(account.account_id)

    assert payload.summary.source_type == "local_snapshot"
    assert payload.summary.source_detail == "local_snapshot_json"
    assert payload.summary.connector_name == "local_codex"


def test_sync_preserves_alias_when_account_identity_is_unchanged(container) -> None:
    account = container.account_service.create_account(
        CreateAccountRequest(account_alias="工作账号", masked_email="user****@example.com")
    )
    service, _ = _make_service(container)

    payload = service.sync_dashboard(account.account_id)

    assert payload.account.account_alias == "工作账号"
    assert container.account_service.get_account(account.account_id).account_alias == "工作账号"


def test_sync_supports_weekly_only_quota(container) -> None:
    account = _make_account(container)
    service, _ = _make_service(container, mode="weekly_only")

    payload = service.sync_dashboard(account.account_id)

    assert [metric.metric_type for metric in payload.metrics] == ["weekly"]
    assert payload.metrics[0].remaining_pct == 89


def test_sync_rejects_unknown_official_windows(container) -> None:
    account = _make_account(container)
    service, _ = _make_service(container, mode="unknown_window")

    with pytest.raises(AnalyticsPageChangedError):
        service.sync_dashboard(account.account_id)
    assert container.account_service.get_account(account.account_id) == account


def test_invalid_first_sync_does_not_create_an_active_account(container) -> None:
    service, _ = _make_service(container, mode="unknown_window")
    with pytest.raises(AnalyticsPageChangedError):
        service.sync_dashboard()
    assert container.account_service.list_accounts() == []


def test_sync_normalizes_known_official_windows(container) -> None:
    account = _make_account(container)
    service, _ = _make_service(container)

    payload = service.sync_dashboard(account.account_id)

    assert [metric.metric_type for metric in payload.metrics] == ["session", "weekly"]
    assert [metric.label for metric in payload.metrics] == ["5h 额度", "周额度"]
    assert [metric.remaining_pct for metric in payload.metrics] == [84, 61]


def test_sync_does_not_expose_raw_window(container) -> None:
    account = _make_account(container)
    service, _ = _make_service(container, mode="sensitive_raw_window")

    payload = service.sync_dashboard(account.account_id)

    dumped = payload.model_dump_json()
    assert "raw_window" not in dumped
    assert "secret-token" not in dumped


def test_auth_failure_is_propagated_without_preemptive_status_change(container) -> None:
    account = _make_account(container)
    service, manager = _make_service(container, mode="expired")

    with pytest.raises(SessionExpiredError):
        service.sync_dashboard(account.account_id)

    assert manager.calls == 1
    assert container.account_service.get_account(account.account_id).status == AccountStatus.ACTIVE
