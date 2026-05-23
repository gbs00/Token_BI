from __future__ import annotations

import re
from typing import Optional

from app.models.account import AccountRecord, AccountStatus, CreateAccountRequest
from app.models.usage_snapshot import (
    DashboardPayload,
    DashboardSummary,
    DetailLink,
    MetricCard,
    PageState,
)
from app.services.account_service import AccountService
from app.services.browser_worker_service import LiveSessionRequiredError
from app.services.cache_service import CacheService
from app.services.scraper_service import (
    AnalyticsPageChangedError,
    ScraperUnavailableError,
    SessionExpiredError,
)
from app.services.session_service import SessionService
from app.services.usage_connectors import (
    ConnectorRateLimitedError,
    UsageConnectorManager,
    normalize_usage_payload,
)


DASHBOARD_METRIC_LABELS = {
    "session": "5h 额度",
    "weekly": "周额度",
}


class UsageService:
    def __init__(
        self,
        account_service: AccountService,
        cache_service: CacheService,
        session_service: SessionService,
        connector_manager: UsageConnectorManager,
    ) -> None:
        self._account_service = account_service
        self._cache_service = cache_service
        self._session_service = session_service
        self._connector_manager = connector_manager

    def get_dashboard(self, account_id: Optional[str] = None, force_refresh: bool = False) -> DashboardPayload:
        account = self._resolve_account(account_id)
        if account is None:
            return self._bootstrap_local_codex_dashboard()

        cache_key = f"usage:{account.account_id}"
        if not force_refresh:
            cached = self._cache_service.get(cache_key)
            if cached is not None:
                return cached
        else:
            self._cache_service.clear(cache_key)

        if not force_refresh and account.status in {AccountStatus.PENDING, AccountStatus.INVALID}:
            return self._build_reauth_required(
                account=account,
                message="Start the live browser worker on Mac and complete the first Codex login.",
            )

        if not force_refresh and account.status == AccountStatus.EXPIRED:
            return self._build_reauth_required(
                account=account,
                message="Live browser session expired on Mac. Please sign in again and keep the worker running.",
            )

        try:
            connector_result = self._connector_manager.fetch_usage(account)
        except LiveSessionRequiredError as exc:
            return self._build_reauth_required(account=account, message=str(exc))
        except SessionExpiredError as exc:
            self._account_service.update_account_status(account.account_id, status="expired")
            return self._build_reauth_required(account=account, message=str(exc))
        except AnalyticsPageChangedError as exc:
            stale = self._build_stale_from_cache(
                cache_key=cache_key,
                account=account,
                message=str(exc),
                state=PageState.SOURCE_CHANGED,
            )
            if stale is not None:
                return stale
            return self._build_error(account=account, message=str(exc), state=PageState.SOURCE_CHANGED)
        except ConnectorRateLimitedError as exc:
            stale = self._build_stale_from_cache(
                cache_key=cache_key,
                account=account,
                message=str(exc),
                state=PageState.RATE_LIMITED,
            )
            if stale is not None:
                return stale
            return self._build_error(account=account, message=str(exc), state=PageState.RATE_LIMITED)
        except ScraperUnavailableError as exc:
            stale = self._build_stale_from_cache(cache_key=cache_key, account=account, message=str(exc))
            if stale is not None:
                return stale
            return self._build_error(account=account, message=str(exc))

        identity = str(connector_result.payload.get("account_masked_email") or "").strip()
        if identity and identity != account.masked_email:
            updated_identity = self._account_service.update_account_identity(
                account.account_id,
                masked_email=identity,
            )
            if updated_identity is not None:
                account = updated_identity

        payload = self._build_ready_payload(
            account=account,
            raw_payload=connector_result.payload,
            connector_name=connector_result.connector_name,
            source_type=connector_result.source_type,
            source_detail=connector_result.source_detail,
        )
        if account.status != AccountStatus.ACTIVE:
            updated_account = self._account_service.update_account_status(
                account.account_id,
                status=AccountStatus.ACTIVE.value,
                update_validation_time=True,
            )
            if updated_account is not None:
                account = updated_account
                payload = payload.model_copy(update={"account": updated_account})
        self._cache_service.set(cache_key, payload)
        return payload

    def refresh_dashboard(self, account_id: Optional[str] = None) -> DashboardPayload:
        return self.get_dashboard(account_id=account_id, force_refresh=True)

    def _resolve_account(self, account_id: Optional[str]) -> Optional[AccountRecord]:
        return self._account_service.preferred_account(account_id)

    def _bootstrap_local_codex_dashboard(self) -> DashboardPayload:
        bootstrap_account = AccountRecord(
            account_id="acc_local_codex",
            account_alias="Codex local account",
            masked_email="Codex local account",
            status=AccountStatus.ACTIVE,
            session_storage_path=str(self._session_service.context_dir("acc_local_codex")),
        )
        try:
            connector_result = self._connector_manager.fetch_usage(bootstrap_account)
        except LiveSessionRequiredError:
            return DashboardPayload(
                state=PageState.EMPTY,
                message="No usage data yet. Complete Codex login authorization on Mac first.",
                detail_links=self._detail_links(),
            )
        except SessionExpiredError as exc:
            return self._build_reauth_required(account=bootstrap_account, message=str(exc))
        except AnalyticsPageChangedError as exc:
            return self._build_error(
                account=bootstrap_account,
                message=str(exc),
                state=PageState.SOURCE_CHANGED,
            )
        except ConnectorRateLimitedError as exc:
            return self._build_error(
                account=bootstrap_account,
                message=str(exc),
                state=PageState.RATE_LIMITED,
            )
        except ScraperUnavailableError as exc:
            return DashboardPayload(
                state=PageState.EMPTY,
                message=str(exc),
                detail_links=self._detail_links(),
            )

        identity = str(connector_result.payload.get("account_masked_email") or "").strip()
        account = self._account_service.create_account(
            CreateAccountRequest(
                account_alias=identity or "Codex local account",
                masked_email=identity or "Codex local account",
            )
        )
        payload = self._build_ready_payload(
            account=account,
            raw_payload=connector_result.payload,
            connector_name=connector_result.connector_name,
            source_type=connector_result.source_type,
            source_detail=connector_result.source_detail,
        )
        updated_account = self._account_service.update_account_status(
            account.account_id,
            status=AccountStatus.ACTIVE.value,
            update_validation_time=True,
        )
        if updated_account is not None:
            payload = payload.model_copy(update={"account": updated_account})
        self._cache_service.set(f"usage:{account.account_id}", payload)
        return payload

    def _build_reauth_required(self, account: AccountRecord, message: str) -> DashboardPayload:
        return DashboardPayload(
            account=account,
            state=PageState.REAUTH_REQUIRED,
            message=message,
            summary=DashboardSummary(
                source_type="scraped",
                source_detail="session_required",
                connector_name="browser_worker",
                is_estimated=True,
            ),
            detail_links=self._detail_links(),
        )

    def _build_error(
        self,
        account: AccountRecord,
        message: str,
        state: PageState = PageState.ERROR,
    ) -> DashboardPayload:
        return DashboardPayload(
            account=account,
            state=state,
            message=message,
            summary=DashboardSummary(
                source_type="unknown",
                source_detail=state.value,
                is_estimated=True,
            ),
            detail_links=self._detail_links(),
        )

    def _build_stale_from_cache(
        self,
        cache_key: str,
        account: AccountRecord,
        message: str,
        state: PageState = PageState.STALE,
    ) -> Optional[DashboardPayload]:
        stale = self._cache_service.get_stale(cache_key)
        if stale is None:
            return None
        return stale.model_copy(
            update={
                "account": account,
                "state": state,
                "message": message,
            }
        )

    def _build_ready_payload(
        self,
        account: AccountRecord,
        raw_payload: dict,
        connector_name: str,
        source_type: str,
        source_detail: str,
    ) -> DashboardPayload:
        normalized_payload = raw_payload
        if "windows" not in raw_payload:
            normalized_payload = normalize_usage_payload(
                raw_payload,
                source_type=source_type,
                source_detail=source_detail,
            )

        metrics: list[MetricCard] = []
        used_metric_types: set[str] = set()
        for window in normalized_payload.get("windows", []):
            if not isinstance(window, dict):
                continue
            metric_type = self._dashboard_metric_type(window)
            if metric_type is None or metric_type in used_metric_types:
                continue
            used_metric_types.add(metric_type)
            metrics.append(
                MetricCard(
                    metric_type=metric_type,
                    label=DASHBOARD_METRIC_LABELS[metric_type],
                    remaining_pct=window.get("remaining_pct"),
                    reset_at=window.get("reset_at"),
                    window_seconds=window.get("window_seconds"),
                    window_minutes=window.get("window_minutes"),
                    source_type=str(window.get("source_type") or source_type),
                    source_detail=str(window.get("source_detail") or source_detail),
                )
            )
        return DashboardPayload(
            account=account,
            state=PageState.READY,
            summary=DashboardSummary(
                updated_at=normalized_payload.get("updated_at"),
                source_type=source_type,
                source_detail=source_detail,
                connector_name=connector_name,
                is_estimated=bool(normalized_payload.get("is_estimated", False)),
            ),
            metrics=metrics,
            detail_links=self._detail_links(),
        )

    def _dashboard_metric_type(self, window: dict) -> Optional[str]:
        metric_type = str(window.get("metric_type") or "").strip().lower()
        if metric_type in DASHBOARD_METRIC_LABELS:
            return metric_type

        display_name = str(window.get("display_name") or "").strip().lower()
        window_minutes = window.get("window_minutes")
        window_seconds = window.get("window_seconds")
        minutes = self._window_minutes(window_minutes=window_minutes, window_seconds=window_seconds)

        if minutes == 300 or "5h" in display_name or "5 h" in display_name or "5-hour" in display_name:
            return "session"
        if minutes == 10080 or "weekly" in display_name or "week" in display_name or "7d" in display_name:
            return "weekly"
        return None

    def _window_minutes(self, window_minutes: object, window_seconds: object) -> Optional[int]:
        if window_minutes is not None:
            try:
                return int(window_minutes)
            except (TypeError, ValueError):
                return None
        if window_seconds is not None:
            try:
                return max(1, int(window_seconds) // 60)
            except (TypeError, ValueError):
                return None
        return None

    def _metric_key(self, window: dict, index: int, used_metric_types: set[str]) -> str:
        legacy_key = window.get("metric_type")
        if isinstance(legacy_key, str) and legacy_key.strip():
            base = legacy_key.strip()
        else:
            display_name = str(window.get("display_name") or "usage-window")
            base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-") or f"window-{index + 1}"
            duration = window.get("window_seconds") or window.get("window_minutes")
            if duration is not None:
                base = f"{base}-{duration}"

        candidate = base
        suffix = 2
        while candidate in used_metric_types:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _detail_links(self) -> list[DetailLink]:
        return [
            DetailLink(
                label="Open Usage",
                url="https://chatgpt.com/codex/cloud/settings/analytics#usage",
                requires_same_account_login=True,
            )
        ]
