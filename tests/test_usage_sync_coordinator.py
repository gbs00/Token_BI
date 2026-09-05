from __future__ import annotations

import json
import stat
import threading
import time
from datetime import datetime, timedelta, timezone

from app.models.account import AccountStatus, CreateAccountRequest
from app.models.usage_snapshot import PageState
from app.services.latest_dashboard_store import LatestDashboardStore
from app.services.usage_connectors import (
    ConnectorChainError,
    ConnectorFailure,
    ConnectorFailureCategory,
    UsageConnectorResult,
)
from app.services.usage_service import UsageService
from app.services.usage_sync_coordinator import UsageSyncCoordinator


class ControlledConnectorManager:
    def __init__(self) -> None:
        self.calls = 0
        self.failure: ConnectorFailure | None = None
        self.started: threading.Event | None = None
        self.release: threading.Event | None = None
        self.identity = "user****@example.com"
        self.unknown_window = False

    def fetch_usage(self, account):
        self.calls += 1
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        if self.failure is not None:
            raise ConnectorChainError(self.failure, [self.failure])
        now = datetime.now(timezone.utc)
        return UsageConnectorResult(
            connector_name="codex_oauth",
            source_type="oauth",
            source_detail="oauth_usage_api",
            payload={
                "account_masked_email": self.identity,
                "updated_at": now,
                "windows": [
                    {
                        "display_name": "Daily" if self.unknown_window else "5h window",
                        "remaining_pct": 82,
                        "reset_at": now + timedelta(hours=4),
                        "window_minutes": 1440 if self.unknown_window else 300,
                    },
                    {
                        "display_name": "Daily" if self.unknown_window else "Weekly",
                        "remaining_pct": 97,
                        "reset_at": now + timedelta(days=6),
                        "window_minutes": 1440 if self.unknown_window else 10080,
                    },
                ],
            },
        )


class RetryOnceConnectorManager(ControlledConnectorManager):
    def fetch_usage(self, account):
        if self.calls == 0:
            self.calls += 1
            failure = _failure(
                ConnectorFailureCategory.TIMEOUT,
                immediate_retry=True,
            )
            raise ConnectorChainError(failure, [failure])
        return super().fetch_usage(account)


def _build_coordinator(container, manager=None, now=None):
    manager = manager or ControlledConnectorManager()
    service = UsageService(
        account_service=container.account_service,
        session_service=container.session_service,
        connector_manager=manager,
    )
    store = LatestDashboardStore(container.settings.runtime_cache_dir / "latest_dashboard.json")
    return UsageSyncCoordinator(service, store, now=now), manager, store


def _create_active_account(container):
    account = container.account_service.create_account(
        CreateAccountRequest(masked_email="user****@example.com")
    )
    return container.account_service.update_account_status(account.account_id, AccountStatus.ACTIVE.value)


def _failure(category, *, immediate_retry=False, retry_after_seconds=None):
    return ConnectorFailure(
        connector_name="codex_oauth",
        category=category,
        error_type="TestConnectorError",
        message="sensitive internal connector detail",
        retry_after_seconds=retry_after_seconds,
        immediate_retry=immediate_retry,
    )


def test_success_is_persisted_as_one_safe_atomic_snapshot(container) -> None:
    _create_active_account(container)
    coordinator, _, store = _build_coordinator(container)

    payload = coordinator.refresh()

    assert payload.state == PageState.READY
    assert store.snapshot_path.exists()
    stored_text = store.snapshot_path.read_text(encoding="utf-8")
    stored = json.loads(stored_text)
    assert stored["account_masked_email"] == "user****@example.com"
    assert "session_storage_path" not in stored_text
    assert "access_token" not in stored_text
    assert "raw_window" not in stored_text
    assert stat.S_IMODE(store.snapshot_path.stat().st_mode) == 0o600
    assert not store.snapshot_path.with_suffix(".json.tmp").exists()


def test_restart_restores_last_success_without_upstream_call(container) -> None:
    account = _create_active_account(container)
    first, manager, store = _build_coordinator(container)
    first.refresh(account.account_id)

    restored, restored_manager, _ = _build_coordinator(container, ControlledConnectorManager())
    payload = restored.get_dashboard(account.account_id)

    assert manager.calls == 1
    assert restored_manager.calls == 0
    assert payload.state == PageState.STALE
    assert [metric.remaining_pct for metric in payload.metrics] == [82, 97]
    assert store.snapshot_path.exists()


def test_identity_mismatch_discards_persisted_snapshot(container) -> None:
    account = _create_active_account(container)
    coordinator, _, store = _build_coordinator(container)
    coordinator.refresh(account.account_id)
    changed = container.account_service.update_account_identity(
        account.account_id,
        "othe****@example.com",
    )

    restored = store.load(changed)

    assert restored is None
    assert not store.snapshot_path.exists()


def test_malformed_snapshot_does_not_break_startup_restore(container) -> None:
    account = _create_active_account(container)
    _, _, store = _build_coordinator(container)
    store.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    store.snapshot_path.write_text("[]", encoding="utf-8")

    restored = store.load(account)

    assert restored is None


def test_dashboard_reads_never_trigger_an_upstream_sync(container) -> None:
    account = _create_active_account(container)
    coordinator, manager, _ = _build_coordinator(container)
    coordinator.refresh(account.account_id)

    payloads = [coordinator.get_dashboard(account.account_id) for _ in range(100)]

    assert manager.calls == 1
    assert all(payload.state == PageState.READY for payload in payloads)


def test_background_coordinator_performs_immediate_async_sync(container) -> None:
    _create_active_account(container)
    manager = ControlledConnectorManager()
    manager.started = threading.Event()
    coordinator, _, _ = _build_coordinator(container, manager)

    coordinator.start()
    try:
        assert manager.started.wait(timeout=1)
        assert manager.calls == 1
    finally:
        coordinator.stop()


def test_transient_failure_preserves_last_success_and_account_state(container) -> None:
    account = _create_active_account(container)
    coordinator, manager, _ = _build_coordinator(container)
    ready = coordinator.refresh(account.account_id)
    manager.failure = _failure(ConnectorFailureCategory.NETWORK_ERROR)

    stale = coordinator.refresh(account.account_id)

    assert stale.state == PageState.STALE
    assert stale.metrics == ready.metrics
    assert "live browser" not in (stale.message or "").lower()
    assert container.account_service.get_account(account.account_id).status == AccountStatus.ACTIVE


def test_only_definitive_auth_failure_marks_account_expired(container) -> None:
    account = _create_active_account(container)
    manager = ControlledConnectorManager()
    manager.failure = _failure(ConnectorFailureCategory.AUTH_REQUIRED)
    coordinator, _, _ = _build_coordinator(container, manager)

    payload = coordinator.refresh(account.account_id)

    assert payload.state == PageState.REAUTH_REQUIRED
    assert container.account_service.get_account(account.account_id).status == AccountStatus.EXPIRED


def test_network_backoff_uses_15_seconds_then_60_seconds(container) -> None:
    account = _create_active_account(container)
    current = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    manager = ControlledConnectorManager()
    manager.failure = _failure(ConnectorFailureCategory.NETWORK_ERROR)
    coordinator, _, _ = _build_coordinator(container, manager, now=lambda: current)

    first = coordinator.refresh(account.account_id)
    second = coordinator.refresh(account.account_id)

    assert first.summary.next_sync_at == current + timedelta(seconds=15)
    assert second.summary.next_sync_at == current + timedelta(seconds=60)


def test_rate_limit_honors_retry_after_with_20_second_minimum(container) -> None:
    account = _create_active_account(container)
    current = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    manager = ControlledConnectorManager()
    manager.failure = _failure(
        ConnectorFailureCategory.RATE_LIMITED,
        retry_after_seconds=45,
    )
    coordinator, _, _ = _build_coordinator(container, manager, now=lambda: current)

    payload = coordinator.refresh(account.account_id)

    assert payload.state == PageState.RATE_LIMITED
    assert payload.summary.next_sync_at == current + timedelta(seconds=45)


def test_timeout_is_retried_once_after_immediate_backoff(container) -> None:
    account = _create_active_account(container)
    manager = RetryOnceConnectorManager()
    coordinator, _, _ = _build_coordinator(container, manager)
    coordinator._wait_for_retry = lambda _delay: True

    payload = coordinator.refresh(account.account_id)

    assert payload.state == PageState.READY
    assert manager.calls == 2


def test_concurrent_refreshes_share_one_upstream_sync(container) -> None:
    account = _create_active_account(container)
    manager = ControlledConnectorManager()
    manager.started = threading.Event()
    manager.release = threading.Event()
    coordinator, _, _ = _build_coordinator(container, manager)
    results = []

    first = threading.Thread(target=lambda: results.append(coordinator.refresh(account.account_id)))
    first.start()
    assert manager.started.wait(timeout=1)
    followers = [
        threading.Thread(target=lambda: results.append(coordinator.refresh(account.account_id)))
        for _ in range(9)
    ]
    for thread in followers:
        thread.start()
    manager.release.set()
    first.join(timeout=2)
    for thread in followers:
        thread.join(timeout=2)

    assert manager.calls == 1
    assert len(results) == 10
    assert all(payload.state == PageState.READY for payload in results)


def test_logout_clear_removes_snapshot_and_visible_metrics(container) -> None:
    account = _create_active_account(container)
    coordinator, _, store = _build_coordinator(container)
    coordinator.refresh(account.account_id)

    container.account_service.delete_account(account.account_id)
    coordinator.clear(account.account_id)

    assert not store.snapshot_path.exists()
    assert coordinator.get_dashboard().metrics == []


def test_failed_account_switch_never_relabels_old_quota(container) -> None:
    account = _create_active_account(container)
    coordinator, manager, store = _build_coordinator(container)
    coordinator.refresh()
    manager.identity = "othe****@example.com"
    manager.unknown_window = True

    failed = coordinator.refresh()

    assert failed.state == PageState.SOURCE_CHANGED
    assert failed.metrics == []
    assert "已保留" not in failed.message
    assert failed.summary.last_success_at is None
    assert not store.snapshot_path.exists()
    assert container.account_service.get_account(account.account_id).masked_email == account.masked_email


def test_memory_snapshot_is_not_reused_after_identity_change(container) -> None:
    account = _create_active_account(container)
    coordinator, _, _ = _build_coordinator(container)
    coordinator.refresh()
    container.account_service.update_account_identity(account.account_id, "othe****@example.com")

    assert coordinator.get_dashboard().metrics == []


def test_logout_stays_disconnected_after_refresh_and_restart(container) -> None:
    _create_active_account(container)
    coordinator, manager, _ = _build_coordinator(container)
    coordinator.refresh()
    coordinator.disconnect()

    assert coordinator.refresh().metrics == []
    assert manager.calls == 1
    restored, restored_manager, _ = _build_coordinator(container)
    assert restored.refresh().metrics == []
    assert restored_manager.calls == 0
    assert restored.get_dashboard().summary.next_sync_at is None
    restored.resume()
    assert restored.refresh().state == PageState.READY
    assert restored_manager.calls == 1


def test_logout_discards_inflight_result_even_after_resuming(container) -> None:
    account = _create_active_account(container)
    manager = ControlledConnectorManager()
    manager.started, manager.release = threading.Event(), threading.Event()
    coordinator, _, store = _build_coordinator(container, manager)
    result = []
    worker = threading.Thread(target=lambda: result.append(coordinator.refresh()))
    worker.start()
    assert manager.started.wait(1)
    coordinator.disconnect()
    container.account_service.delete_account(account.account_id)
    coordinator.resume()
    manager.release.set()
    worker.join(2)

    assert not worker.is_alive()
    assert result[0].metrics == []
    assert container.account_service.list_accounts() == []
    assert not store.snapshot_path.exists()


def test_full_sync_deadline_releases_callers_and_discards_late_result(container, monkeypatch) -> None:
    _create_active_account(container)
    manager = ControlledConnectorManager()
    manager.started, manager.release = threading.Event(), threading.Event()
    coordinator, _, store = _build_coordinator(container, manager)
    monkeypatch.setattr(coordinator, "SYNC_TIMEOUT_SECONDS", 0.08)
    started = time.monotonic()
    try:
        failed = coordinator.refresh()
        assert time.monotonic() - started < 0.5
        assert failed.state == PageState.ERROR
        assert not store.snapshot_path.exists()
        assert coordinator.refresh().state != PageState.READY
        assert manager.calls == 1  # 未结束的采集不能不断产生新的线程。
    finally:
        manager.release.set()
    for _ in range(100):
        if coordinator._fetch_done.wait(0.01):
            break
    assert coordinator.get_dashboard().metrics == []
    assert coordinator.refresh().state == PageState.READY


def test_unexpected_sync_error_is_not_reported_as_ready(container) -> None:
    _create_active_account(container)
    coordinator, manager, _ = _build_coordinator(container)
    ready = coordinator.refresh()
    def fail(_account):
        raise ValueError("sensitive detail")
    manager.fetch_usage = fail

    failed = coordinator.refresh()

    assert failed.state == PageState.STALE
    assert failed.metrics == ready.metrics
    assert failed.summary.last_success_at == ready.summary.last_success_at
    assert "sensitive" not in failed.message


def test_account_write_failure_is_visible_as_failed_sync(container, monkeypatch):
    _create_active_account(container)
    coordinator, _, _ = _build_coordinator(container)
    coordinator.refresh()
    def fail(*_args):
        raise OSError("synthetic write failure")
    monkeypatch.setattr(container.account_service, "commit_synced_account", fail)
    assert coordinator.refresh().state == PageState.STALE
    assert coordinator.get_dashboard().state == PageState.STALE


def test_account_fingerprint_invalidates_memory_and_disk_cache(container):
    from app.models.account import identity_key
    account = _create_active_account(container)
    coordinator, _, store = _build_coordinator(container)
    coordinator.refresh()
    changed = account.model_copy(update={"identity_key": identity_key("user.two@example.com")})
    container.account_service._write_accounts([changed])
    assert coordinator.get_dashboard().metrics == []
    assert not store.snapshot_path.exists()
