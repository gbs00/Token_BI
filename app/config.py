from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    config_dir: Path
    runtime_dir: Path
    runtime_contexts_dir: Path
    runtime_cache_dir: Path
    runtime_local_connector_dir: Path
    runtime_logs_dir: Path
    templates_dir: Path
    static_dir: Path
    accounts_file: Path
    host: str
    port: int
    cache_ttl_seconds: int
    analytics_url: str
    manual_login_url: str
    browser_app_name: str
    browser_debug_host: str
    browser_debug_base_port: int
    playwright_channel: str
    playwright_headless: bool
    scrape_timeout_ms: int
    mock_scraper_enabled: bool

    def ensure_directories(self) -> None:
        for directory in (
            self.config_dir,
            self.runtime_dir,
            self.runtime_contexts_dir,
            self.runtime_cache_dir,
            self.runtime_local_connector_dir,
            self.runtime_logs_dir,
            self.templates_dir,
            self.static_dir,
            self.static_dir / "css",
            self.static_dir / "js",
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    config_dir = project_root / "config"
    runtime_dir = project_root / "runtime"
    templates_dir = project_root / "app" / "templates"
    static_dir = project_root / "app" / "static"

    settings = Settings(
        project_root=project_root,
        config_dir=config_dir,
        runtime_dir=runtime_dir,
        runtime_contexts_dir=runtime_dir / "contexts",
        runtime_cache_dir=runtime_dir / "cache",
        runtime_local_connector_dir=runtime_dir / "cache" / "local_codex",
        runtime_logs_dir=runtime_dir / "logs",
        templates_dir=templates_dir,
        static_dir=static_dir,
        accounts_file=config_dir / "accounts.json",
        host=os.getenv("TOKEN_BI_HOST", "0.0.0.0"),
        port=int(os.getenv("TOKEN_BI_PORT", "8787")),
        cache_ttl_seconds=int(os.getenv("TOKEN_BI_CACHE_TTL", "90")),
        analytics_url=os.getenv(
            "TOKEN_BI_ANALYTICS_URL",
            "https://chatgpt.com/codex/cloud/settings/analytics#usage",
        ),
        manual_login_url=os.getenv(
            "TOKEN_BI_MANUAL_LOGIN_URL",
            "https://chatgpt.com/#usage",
        ),
        browser_app_name=os.getenv("TOKEN_BI_BROWSER_APP_NAME", "Google Chrome"),
        browser_debug_host=os.getenv("TOKEN_BI_BROWSER_DEBUG_HOST", "127.0.0.1"),
        browser_debug_base_port=int(os.getenv("TOKEN_BI_BROWSER_DEBUG_BASE_PORT", "9222")),
        playwright_channel=os.getenv("TOKEN_BI_PLAYWRIGHT_CHANNEL", "msedge"),
        playwright_headless=os.getenv("TOKEN_BI_PLAYWRIGHT_HEADLESS", "true").lower()
        in {"1", "true", "yes"},
        scrape_timeout_ms=int(os.getenv("TOKEN_BI_SCRAPE_TIMEOUT_MS", "15000")),
        mock_scraper_enabled=os.getenv("TOKEN_BI_USE_MOCK_SCRAPER", "false").lower()
        in {"1", "true", "yes"},
    )
    settings.ensure_directories()
    return settings
