from __future__ import annotations

from app.config import Settings
from app.services.account_service import AccountService
from app.services.browser_worker_service import BrowserWorkerService
from app.services.cache_service import CacheService
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


class ServiceContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.account_service = AccountService(settings)
        self.cache_service = CacheService(default_ttl_seconds=settings.cache_ttl_seconds)
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
            cache_service=self.cache_service,
            session_service=self.session_service,
            connector_manager=self.usage_connector_manager,
        )

    def startup(self) -> None:
        for account in self.account_service.list_visible_accounts():
            if account.status.value != "active":
                continue
            try:
                self.browser_worker_service.restore_session_snapshot(account)
            except Exception:
                continue

    def shutdown(self) -> None:
        self.browser_worker_service.shutdown()
