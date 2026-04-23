from __future__ import annotations

from app.config import Settings
from app.services.account_service import AccountService
from app.services.browser_worker_service import BrowserWorkerService
from app.services.cache_service import CacheService
from app.services.scraper_service import ScraperService
from app.services.session_service import SessionService
from app.services.usage_connectors import (
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
        self.usage_connector_manager = UsageConnectorManager(
            connectors=[
                LocalCodexConnector(settings.runtime_local_connector_dir),
                WebSessionConnector(self.browser_worker_service),
            ]
        )
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
                self.browser_worker_service.ensure_worker_for_account(
                    account,
                    target_url=self.settings.analytics_url,
                )
            except Exception:
                continue

    def shutdown(self) -> None:
        self.browser_worker_service.shutdown()
