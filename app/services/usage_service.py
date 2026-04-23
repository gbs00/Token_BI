from __future__ import annotations

from typing import Optional

from app.models.account import AccountRecord, AccountStatus
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
from app.services.usage_connectors import UsageConnectorManager


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
            return DashboardPayload(
                state=PageState.EMPTY,
                message="No usage data yet. Add a Codex account on Mac first.",
                detail_links=[],
            )

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
            stale = self._build_stale_from_cache(cache_key=cache_key, account=account, message=str(exc))
            if stale is not None:
                return stale
            return self._build_error(account=account, message=str(exc))
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

    def _build_error(self, account: AccountRecord, message: str) -> DashboardPayload:
        return DashboardPayload(
            account=account,
            state=PageState.ERROR,
            message=message,
            summary=DashboardSummary(
                source_type="scraped",
                source_detail="connector_error",
                is_estimated=True,
            ),
            detail_links=self._detail_links(),
        )

    def _build_stale_from_cache(
        self,
        cache_key: str,
        account: AccountRecord,
        message: str,
    ) -> Optional[DashboardPayload]:
        stale = self._cache_service.get_stale(cache_key)
        if stale is None:
            return None
        return stale.model_copy(
            update={
                "account": account,
                "state": PageState.STALE,
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
        metrics = [
            MetricCard(
                metric_type="session",
                label="5h Session",
                remaining_pct=raw_payload.get("session_remaining_pct"),
                reset_at=raw_payload.get("session_reset_at"),
            ),
            MetricCard(
                metric_type="weekly",
                label="Weekly",
                remaining_pct=raw_payload.get("weekly_remaining_pct"),
                reset_at=raw_payload.get("weekly_reset_at"),
            ),
        ]
        return DashboardPayload(
            account=account,
            state=PageState.READY,
            summary=DashboardSummary(
                updated_at=raw_payload.get("updated_at"),
                source_type=source_type,
                source_detail=source_detail,
                connector_name=connector_name,
                is_estimated=bool(raw_payload.get("is_estimated", False)),
            ),
            metrics=metrics,
            detail_links=self._detail_links(),
        )

    def _detail_links(self) -> list[DetailLink]:
        return [
            DetailLink(
                label="Open Usage",
                url="https://chatgpt.com/codex/cloud/settings/analytics#usage",
                requires_same_account_login=True,
            )
        ]
