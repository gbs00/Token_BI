from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
        if self.mode == "ready":
            now = datetime.now(timezone.utc)
            return UsageConnectorResult(
                connector_name="web_session",
                source_type="scraped",
                source_detail="network_response",
                payload={
                    "session_remaining_pct": 100,
                    "session_reset_at": now + timedelta(hours=5),
                    "weekly_remaining_pct": 92,
                    "weekly_reset_at": now + timedelta(days=6),
                    "updated_at": now,
                    "is_estimated": False,
                },
            )
        if self.mode == "local":
            now = datetime.now(timezone.utc)
            return UsageConnectorResult(
                connector_name="local_codex",
                source_type="local_snapshot",
                source_detail="local_snapshot_json",
                payload={
                    "session_remaining_pct": 77,
                    "session_reset_at": now + timedelta(hours=3),
                    "weekly_remaining_pct": 61,
                    "weekly_reset_at": now + timedelta(days=4),
                    "updated_at": now,
                    "is_estimated": False,
                },
            )
        if self.mode == "weekly_only":
            now = datetime.now(timezone.utc)
            return UsageConnectorResult(
                connector_name="web_session",
                source_type="scraped",
                source_detail="network_response",
                payload={
                    "weekly_remaining_pct": 89,
                    "weekly_reset_at": now + timedelta(days=5),
                    "updated_at": now,
                    "is_estimated": False,
                },
            )
        if self.mode == "official_single_window":
            now = datetime.now(timezone.utc)
            return UsageConnectorResult(
                connector_name="codex_oauth",
                source_type="oauth",
                source_detail="oauth_usage_api",
                payload={
                    "account_masked_email": "user****@example.com",
                    "updated_at": now,
                    "is_estimated": False,
                    "windows": [
                        {
                            "display_name": "Codex Pro window",
                            "remaining_pct": 58,
                            "reset_at": now + timedelta(hours=7),
                            "window_seconds": 25200,
                            "window_minutes": 420,
                            "source_type": "oauth",
                            "source_detail": "oauth_usage_api",
                        }
                    ],
                },
            )
        if self.mode == "official_known_windows":
            now = datetime.now(timezone.utc)
            return UsageConnectorResult(
                connector_name="codex_oauth",
                source_type="oauth",
                source_detail="oauth_usage_api",
                payload={
                    "updated_at": now,
                    "is_estimated": False,
                    "windows": [
                        {
                            "display_name": "5h window",
                            "remaining_pct": 84,
                            "reset_at": now + timedelta(hours=3),
                            "window_minutes": 300,
                            "source_type": "oauth",
                            "source_detail": "oauth_usage_api",
                        },
                        {
                            "display_name": "Weekly",
                            "remaining_pct": 61,
                            "reset_at": now + timedelta(days=4),
                            "window_seconds": 604800,
                            "source_type": "oauth",
                            "source_detail": "oauth_usage_api",
                        },
                    ],
                },
            )
        if self.mode == "sensitive_raw_window":
            now = datetime.now(timezone.utc)
            return UsageConnectorResult(
                connector_name="codex_oauth",
                source_type="oauth",
                source_detail="oauth_usage_api",
                payload={
                    "updated_at": now,
                    "is_estimated": False,
                    "windows": [
                        {
                            "raw_window": {"access_token": "secret-token"},
                            "display_name": "Codex window",
                            "remaining_pct": 50,
                            "reset_at": now + timedelta(hours=1),
                            "source_type": "oauth",
                            "source_detail": "oauth_usage_api",
                        }
                    ],
                },
            )
        if self.mode == "structure_changed":
            raise AnalyticsPageChangedError("Analytics page may have changed.")
        if self.mode == "expired":
            raise SessionExpiredError("Session expired on Mac. Please sign in again on Mac.")
        raise RuntimeError("Unknown connector mode")


def _make_active_account(container):
    account = container.account_service.create_account(
        CreateAccountRequest(masked_email="guo****@gmail.com")
    )
    container.session_service.ensure_context_dir(account.account_id)
    marker = container.session_service.context_dir(account.account_id) / "state.json"
    marker.write_text("ok", encoding="utf-8")
    updated = container.account_service.update_account_status(account.account_id, AccountStatus.ACTIVE.value)
    return updated


def test_usage_service_returns_empty_when_no_accounts(container) -> None:
    payload = container.usage_service.get_dashboard()
    assert payload.state == PageState.EMPTY


def test_usage_service_bootstraps_local_codex_account_when_no_records(container) -> None:
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="official_single_window"),
    )

    payload = service.get_dashboard()
    accounts = container.account_service.list_accounts()

    assert payload.state == PageState.SOURCE_CHANGED
    assert payload.account is not None
    assert payload.account.status == AccountStatus.ACTIVE
    assert payload.account.masked_email == "user****@example.com"
    assert [account.masked_email for account in accounts] == ["user****@example.com"]
    assert payload.metrics == []


def test_usage_service_updates_pending_account_from_local_codex_identity(container) -> None:
    stale_account = container.account_service.create_account(
        CreateAccountRequest(masked_email="Lark...")
    )
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="official_single_window"),
    )

    payload = service.get_dashboard()
    accounts = container.account_service.list_accounts()

    assert payload.state == PageState.SOURCE_CHANGED
    assert payload.account is not None
    assert payload.account.account_id == stale_account.account_id
    assert payload.account.status == AccountStatus.ACTIVE
    assert payload.account.masked_email == "user****@example.com"
    assert len(accounts) == 1
    assert accounts[0].masked_email == "user****@example.com"


def test_usage_service_returns_ready_and_caches(container) -> None:
    account = _make_active_account(container)
    connector_manager = FakeConnectorManager(mode="ready")
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=connector_manager,
    )

    first = service.get_dashboard(account.account_id)
    second = service.get_dashboard(account.account_id)

    assert first.state == PageState.READY
    assert second.state == PageState.READY
    assert first.summary.source_detail == "network_response"
    assert connector_manager.calls == 1


def test_usage_service_uses_connector_metadata(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="local"),
    )

    payload = service.get_dashboard(account.account_id)

    assert payload.state == PageState.READY
    assert payload.summary.source_type == "local_snapshot"
    assert payload.summary.source_detail == "local_snapshot_json"
    assert payload.summary.connector_name == "local_codex"


def test_usage_service_omits_session_metric_when_only_weekly_quota_exists(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="weekly_only"),
    )

    payload = service.get_dashboard(account.account_id)

    assert payload.state == PageState.READY
    assert [metric.metric_type for metric in payload.metrics] == ["weekly"]
    assert payload.metrics[0].remaining_pct == 89


def test_usage_service_filters_unknown_official_windows_from_dashboard_metrics(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="official_single_window"),
    )

    payload = service.get_dashboard(account.account_id)

    assert payload.state == PageState.SOURCE_CHANGED
    assert payload.metrics == []


def test_usage_service_normalizes_known_official_windows_for_dashboard(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="official_known_windows"),
    )

    payload = service.get_dashboard(account.account_id)

    assert payload.state == PageState.READY
    assert [metric.metric_type for metric in payload.metrics] == ["session", "weekly"]
    assert [metric.label for metric in payload.metrics] == ["5h 额度", "周额度"]
    assert [metric.remaining_pct for metric in payload.metrics] == [84, 61]
    assert [metric.source_type for metric in payload.metrics] == ["oauth", "oauth"]


def test_usage_service_does_not_expose_raw_window_in_dashboard_payload(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="sensitive_raw_window"),
    )

    payload = service.get_dashboard(account.account_id)

    dumped = payload.model_dump_json()
    assert "raw_window" not in dumped
    assert "secret-token" not in dumped


def test_usage_service_returns_stale_when_fetch_fails_after_success(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="ready"),
    )
    ready = service.get_dashboard(account.account_id)
    assert ready.state == PageState.READY
    container.cache_service.clear()
    container.cache_service.set(f"usage:{account.account_id}", ready, ttl_seconds=-1)

    failing_service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="structure_changed"),
    )
    stale = failing_service.get_dashboard(account.account_id)
    assert stale.state == PageState.SOURCE_CHANGED
    assert stale.message == "Analytics page may have changed."


def test_force_refresh_preserves_last_good_payload_when_fetch_fails(container) -> None:
    account = _make_active_account(container)
    ready_service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="ready"),
    )
    ready = ready_service.get_dashboard(account.account_id)

    failing_service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="structure_changed"),
    )
    stale = failing_service.refresh_dashboard(account.account_id)

    assert stale.state == PageState.SOURCE_CHANGED
    assert stale.metrics == ready.metrics
    assert stale.summary.updated_at == ready.summary.updated_at
    assert failing_service.get_cached_dashboard(account.account_id) == ready


def test_usage_service_marks_session_expired(container) -> None:
    account = _make_active_account(container)
    service = UsageService(
        account_service=container.account_service,
        cache_service=container.cache_service,
        session_service=container.session_service,
        connector_manager=FakeConnectorManager(mode="expired"),
    )

    payload = service.get_dashboard(account.account_id)
    refreshed = container.account_service.get_account(account.account_id)
    assert payload.state == PageState.REAUTH_REQUIRED
    assert refreshed is not None
    assert refreshed.status == AccountStatus.EXPIRED
