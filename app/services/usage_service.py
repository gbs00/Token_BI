from __future__ import annotations

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
from app.services.scraper_service import AnalyticsPageChangedError
from app.services.session_service import SessionService
from app.services.usage_connectors import (
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
        session_service: SessionService,
        connector_manager: UsageConnectorManager,
    ) -> None:
        self._account_service = account_service
        self._session_service = session_service
        self._connector_manager = connector_manager

    def sync_dashboard(self, account_id: Optional[str] = None) -> DashboardPayload:
        account = self._resolve_account(account_id)
        if account is None:
            account = self._bootstrap_account()

        connector_result = self._connector_manager.fetch_usage(account)

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
        if account.account_id == "acc_local_codex":
            account = self._account_service.create_account(
                CreateAccountRequest(
                    account_alias=identity or "Codex local account",
                    masked_email=identity or "Codex local account",
                )
            )
            payload = payload.model_copy(update={"account": account})

        if account.status != AccountStatus.ACTIVE:
            updated_account = self._account_service.update_account_status(
                account.account_id,
                status=AccountStatus.ACTIVE.value,
                update_validation_time=True,
            )
            if updated_account is not None:
                account = updated_account
                payload = payload.model_copy(update={"account": updated_account})
        if not payload.metrics:
            raise AnalyticsPageChangedError("官方返回的额度窗口暂不支持展示。")
        return payload

    def _resolve_account(self, account_id: Optional[str]) -> Optional[AccountRecord]:
        return self._account_service.preferred_account(account_id)

    def current_account(self, account_id: Optional[str] = None) -> Optional[AccountRecord]:
        return self._resolve_account(account_id)

    def mark_account_expired(self, account_id: str) -> Optional[AccountRecord]:
        return self._account_service.update_account_status(
            account_id,
            AccountStatus.EXPIRED.value,
        )

    def empty_dashboard(self, message: Optional[str] = None) -> DashboardPayload:
        return DashboardPayload(
            account=self._resolve_account(None),
            state=PageState.EMPTY,
            message=message or "等待首次同步，Token BI 将自动读取本机 Codex 登录态。",
            detail_links=self._detail_links(),
        )

    def _bootstrap_account(self) -> AccountRecord:
        return AccountRecord(
            account_id="acc_local_codex",
            account_alias="Codex local account",
            masked_email="Codex local account",
            status=AccountStatus.ACTIVE,
            session_storage_path=str(self._session_service.context_dir("acc_local_codex")),
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

    def _detail_links(self) -> list[DetailLink]:
        return [
            DetailLink(
                label="Open Usage",
                url="https://chatgpt.com/codex/cloud/settings/analytics#usage",
                requires_same_account_login=True,
            )
        ]
