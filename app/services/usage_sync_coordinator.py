from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.models.usage_snapshot import DashboardPayload, DashboardSummary, PageState
from app.services.browser_worker_service import LiveSessionRequiredError
from app.services.latest_dashboard_store import LatestDashboardStore
from app.services.scraper_service import (
    AnalyticsPageChangedError,
    ScraperUnavailableError,
    SessionExpiredError,
)
from app.services.usage_connectors import (
    ConnectorChainError,
    ConnectorFailure,
    ConnectorFailureCategory,
    ConnectorNetworkError,
    ConnectorNotApplicableError,
    ConnectorRateLimitedError,
    ConnectorTimeoutError,
)
from app.services.usage_service import UsageService


logger = logging.getLogger(__name__)


class UsageSyncCoordinator:
    SUCCESS_INTERVAL_SECONDS = 180.0
    NETWORK_FIRST_RETRY_SECONDS = 15.0
    FAILURE_RETRY_SECONDS = 60.0
    IMMEDIATE_RETRY_SECONDS = 2.0
    RATE_LIMIT_MIN_RETRY_SECONDS = 20.0

    def __init__(
        self,
        usage_service: UsageService,
        snapshot_store: LatestDashboardStore,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._usage_service = usage_service
        self._snapshot_store = snapshot_store
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._state_lock = threading.RLock()
        self._sync_condition = threading.Condition(threading.RLock())
        self._stop_event = threading.Event()
        self._schedule_changed = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._syncing = False
        self._consecutive_failures = 0

        account = self._usage_service.current_account()
        restored = self._snapshot_store.load(account)
        if restored is not None:
            now_value = self._now()
            self._current = restored.model_copy(
                update={
                    "state": PageState.STALE,
                    "message": "正在同步最新额度，当前展示上次成功数据。",
                    "summary": restored.summary.model_copy(update={"next_sync_at": now_value}),
                }
            )
        else:
            self._current = self._with_schedule(
                self._usage_service.empty_dashboard(),
                last_attempt_at=None,
                last_success_at=None,
                next_sync_at=self._now(),
            )

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="token-bi-usage-sync",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._schedule_changed.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def get_dashboard(self, account_id: Optional[str] = None) -> DashboardPayload:
        account = self._usage_service.current_account(account_id)
        with self._state_lock:
            current = self._current
        if account is None:
            return current if current.account is None else self._usage_service.empty_dashboard()
        if current.account is None or current.account.account_id != account.account_id:
            restored = self._snapshot_store.load(account)
            if restored is None:
                current = self._with_schedule(
                    self._usage_service.empty_dashboard(),
                    last_attempt_at=None,
                    last_success_at=None,
                    next_sync_at=self._now(),
                ).model_copy(update={"account": account})
            else:
                current = restored.model_copy(update={"state": PageState.STALE})
            with self._state_lock:
                self._current = current
        return current.model_copy(update={"account": account})

    def refresh(self, account_id: Optional[str] = None) -> DashboardPayload:
        with self._sync_condition:
            if self._syncing:
                self._sync_condition.wait_for(lambda: not self._syncing)
                return self.get_dashboard(account_id)
            self._syncing = True

        try:
            return self._perform_refresh(account_id)
        finally:
            with self._sync_condition:
                self._syncing = False
                self._sync_condition.notify_all()

    def clear(self, account_id: Optional[str] = None) -> None:
        self._snapshot_store.clear(account_id)
        with self._state_lock:
            self._consecutive_failures = 0
            self._current = self._with_schedule(
                self._usage_service.empty_dashboard(),
                last_attempt_at=None,
                last_success_at=None,
                next_sync_at=self._now(),
            )
        self._schedule_changed.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            delay = self._seconds_until_next_sync()
            if delay > 0:
                self._schedule_changed.wait(timeout=delay)
                self._schedule_changed.clear()
                continue
            try:
                self.refresh()
            except Exception:
                logger.exception("usage_sync_unhandled_error")
                self._schedule_after_unhandled_error()

    def _seconds_until_next_sync(self) -> float:
        with self._state_lock:
            next_sync_at = self._current.summary.next_sync_at
        if next_sync_at is None:
            return 0.0
        return max(0.0, (next_sync_at - self._now()).total_seconds())

    def _perform_refresh(self, account_id: Optional[str]) -> DashboardPayload:
        attempt_at = self._now()
        try:
            payload = self._usage_service.sync_dashboard(account_id)
        except ScraperUnavailableError as exc:
            failure = self._normalize_failure(exc)
            if failure.immediate_retry and self._wait_for_retry(self.IMMEDIATE_RETRY_SECONDS):
                attempt_at = self._now()
                try:
                    payload = self._usage_service.sync_dashboard(account_id)
                except ScraperUnavailableError as retry_exc:
                    return self._record_failure(
                        self._normalize_failure(retry_exc),
                        attempt_at,
                        account_id,
                    )
            else:
                return self._record_failure(failure, attempt_at, account_id)

        completed_at = self._now()
        ready = self._with_schedule(
            payload.model_copy(update={"state": PageState.READY, "message": None}),
            last_attempt_at=attempt_at,
            last_success_at=completed_at,
            next_sync_at=completed_at + timedelta(seconds=self.SUCCESS_INTERVAL_SECONDS),
        )
        with self._state_lock:
            self._current = ready
            self._consecutive_failures = 0
        try:
            self._snapshot_store.save(ready)
        except OSError:
            logger.exception("usage_snapshot_persist_failed")
        self._schedule_changed.set()
        logger.info(
            "usage_sync_success connector=%s source=%s",
            ready.summary.connector_name or "unknown",
            ready.summary.source_type,
        )
        return ready

    def _record_failure(
        self,
        failure: ConnectorFailure,
        attempt_at: datetime,
        account_id: Optional[str],
    ) -> DashboardPayload:
        with self._state_lock:
            self._consecutive_failures += 1
            retry_seconds = self._retry_delay(failure, self._consecutive_failures)
            current = self._current

        next_sync_at = self._now() + timedelta(seconds=retry_seconds)
        account = self._usage_service.current_account(account_id)
        if failure.category == ConnectorFailureCategory.AUTH_REQUIRED and account is not None:
            updated = self._usage_service.mark_account_expired(account.account_id)
            if updated is not None:
                account = updated

        page_state = self._page_state_for_failure(failure.category, has_stale=bool(current.metrics))
        message = self._public_message(failure.category)
        if current.metrics:
            failed = current.model_copy(
                update={
                    "account": account or current.account,
                    "state": page_state,
                    "message": message,
                }
            )
        else:
            failed = DashboardPayload(
                account=account,
                state=page_state,
                message=message,
                summary=DashboardSummary(
                    source_type="unknown",
                    source_detail=failure.category.value,
                    is_estimated=True,
                ),
                detail_links=current.detail_links,
            )
        failed = self._with_schedule(
            failed,
            last_attempt_at=attempt_at,
            last_success_at=current.summary.last_success_at,
            next_sync_at=next_sync_at,
        )
        with self._state_lock:
            self._current = failed
        self._schedule_changed.set()
        logger.warning(
            "usage_sync_failed category=%s connector=%s retry_seconds=%s",
            failure.category.value,
            failure.connector_name,
            int(retry_seconds),
        )
        return failed

    def _normalize_failure(self, exc: ScraperUnavailableError) -> ConnectorFailure:
        if isinstance(exc, ConnectorChainError):
            return exc.primary_failure
        category = ConnectorFailureCategory.INTERNAL_ERROR
        if isinstance(exc, SessionExpiredError):
            category = ConnectorFailureCategory.AUTH_REQUIRED
        elif isinstance(exc, ConnectorRateLimitedError):
            category = ConnectorFailureCategory.RATE_LIMITED
        elif isinstance(exc, AnalyticsPageChangedError):
            category = ConnectorFailureCategory.SOURCE_CHANGED
        elif isinstance(exc, ConnectorTimeoutError):
            category = ConnectorFailureCategory.TIMEOUT
        elif isinstance(exc, ConnectorNetworkError):
            category = ConnectorFailureCategory.NETWORK_ERROR
        elif isinstance(exc, LiveSessionRequiredError):
            category = ConnectorFailureCategory.WEB_SESSION_INACTIVE
        elif isinstance(exc, ConnectorNotApplicableError):
            category = ConnectorFailureCategory.NOT_APPLICABLE
        return ConnectorFailure(
            connector_name="usage_service",
            category=category,
            error_type=exc.__class__.__name__,
            message=str(exc),
            retry_after_seconds=getattr(exc, "retry_after_seconds", None),
            immediate_retry=bool(getattr(exc, "immediate_retry", False)),
        )

    def _retry_delay(self, failure: ConnectorFailure, consecutive_failures: int) -> float:
        if failure.category == ConnectorFailureCategory.RATE_LIMITED:
            return max(
                self.RATE_LIMIT_MIN_RETRY_SECONDS,
                failure.retry_after_seconds or 0.0,
            )
        if failure.category in {
            ConnectorFailureCategory.NETWORK_ERROR,
            ConnectorFailureCategory.TIMEOUT,
        } and consecutive_failures == 1:
            return self.NETWORK_FIRST_RETRY_SECONDS
        return self.FAILURE_RETRY_SECONDS

    def _wait_for_retry(self, delay_seconds: float) -> bool:
        return not self._stop_event.wait(timeout=delay_seconds)

    def _schedule_after_unhandled_error(self) -> None:
        with self._state_lock:
            self._current = self._with_schedule(
                self._current,
                last_attempt_at=self._now(),
                last_success_at=self._current.summary.last_success_at,
                next_sync_at=self._now() + timedelta(seconds=self.FAILURE_RETRY_SECONDS),
            )

    def _with_schedule(
        self,
        payload: DashboardPayload,
        last_attempt_at: Optional[datetime],
        last_success_at: Optional[datetime],
        next_sync_at: datetime,
    ) -> DashboardPayload:
        summary = payload.summary.model_copy(
            update={
                "last_attempt_at": last_attempt_at,
                "last_success_at": last_success_at,
                "next_sync_at": next_sync_at,
            }
        )
        return payload.model_copy(update={"summary": summary})

    def _page_state_for_failure(
        self,
        category: ConnectorFailureCategory,
        has_stale: bool,
    ) -> PageState:
        if category == ConnectorFailureCategory.AUTH_REQUIRED:
            return PageState.REAUTH_REQUIRED
        if category == ConnectorFailureCategory.RATE_LIMITED:
            return PageState.RATE_LIMITED
        if category == ConnectorFailureCategory.SOURCE_CHANGED:
            return PageState.SOURCE_CHANGED
        if category in {
            ConnectorFailureCategory.WEB_SESSION_INACTIVE,
            ConnectorFailureCategory.NOT_APPLICABLE,
        }:
            return PageState.REAUTH_REQUIRED
        return PageState.STALE if has_stale else PageState.ERROR

    def _public_message(self, category: ConnectorFailureCategory) -> str:
        if category == ConnectorFailureCategory.AUTH_REQUIRED:
            return "未检测到可用的 Codex 登录态，请在 Codex App、CLI 或网页端完成登录。"
        if category == ConnectorFailureCategory.RATE_LIMITED:
            return "Codex 额度接口暂时限流，Token BI 将自动重试。"
        if category == ConnectorFailureCategory.SOURCE_CHANGED:
            return "官方额度数据格式发生变化，已保留上次成功数据。"
        if category in {
            ConnectorFailureCategory.WEB_SESSION_INACTIVE,
            ConnectorFailureCategory.NOT_APPLICABLE,
        }:
            return "暂无可用的 Codex 登录态，请在 Mac 端登录后重试。"
        return "Codex 数据源暂时不可用，Token BI 将自动重试。"
