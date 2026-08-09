from __future__ import annotations

from app.config import Settings
from app.services.account_service import AccountService
from app.services.browser_worker_service import BrowserWorkerService
from app.services.latest_dashboard_store import LatestDashboardStore
from app.services.scraper_service import ScraperService
from app.services.session_service import SessionService
from app.services.usage_connectors import (
    CodexCliRpcConnector,
    CodexOAuthConnector,
    LocalCodexConnector,
    UsageConnectorManager,
    WebSessionConnector,
)
from app.services.usage_service import UsageService
from app.services.usage_sync_coordinator import UsageSyncCoordinator


class ServiceContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.account_service = AccountService(settings)
        self.session_service = SessionService(settings)
        self.scraper_service = ScraperService(settings)
        self.browser_worker_service = BrowserWorkerService(settings, self.scraper_service)
        usage_connectors = [
            CodexOAuthConnector(
                auth_paths=settings.codex_auth_paths,
                usage_url=settings.codex_oauth_usage_url,
                timeout_seconds=settings.codex_cli_timeout_seconds,
            ),
            CodexCliRpcConnector(
                codex_bin=settings.codex_cli_bin,
                timeout_seconds=settings.codex_cli_timeout_seconds,
            ),
        ]
        if settings.local_snapshot_connector_enabled:
            usage_connectors.append(LocalCodexConnector(settings.runtime_local_connector_dir))
        usage_connectors.append(WebSessionConnector(self.browser_worker_service))
        self.usage_connector_manager = UsageConnectorManager(connectors=usage_connectors)
        self.usage_service = UsageService(
            account_service=self.account_service,
            session_service=self.session_service,
            connector_manager=self.usage_connector_manager,
        )
        self.latest_dashboard_store = LatestDashboardStore(
            settings.runtime_cache_dir / "latest_dashboard.json"
        )
        self.usage_sync_coordinator = UsageSyncCoordinator(
            usage_service=self.usage_service,
            snapshot_store=self.latest_dashboard_store,
        )

    def startup(self) -> None:
        for account in self.account_service.list_visible_accounts():
            if account.status.value != "active":
                continue
            try:
                self.browser_worker_service.restore_session_snapshot(account)
            except Exception:
                continue
        self.usage_sync_coordinator.start()

    def shutdown(self) -> None:
        self.usage_sync_coordinator.stop()
        self.browser_worker_service.shutdown()
