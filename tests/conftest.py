from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.container import ServiceContainer
from app.main import create_app


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    project_root = tmp_path
    settings = Settings(
        project_root=project_root,
        config_dir=project_root / "config",
        runtime_dir=project_root / "runtime",
        runtime_contexts_dir=project_root / "runtime" / "contexts",
        runtime_cache_dir=project_root / "runtime" / "cache",
        runtime_local_connector_dir=project_root / "runtime" / "cache" / "local_codex",
        runtime_logs_dir=project_root / "runtime" / "logs",
        templates_dir=PROJECT_ROOT / "app" / "templates",
        static_dir=PROJECT_ROOT / "app" / "static",
        accounts_file=project_root / "config" / "accounts.json",
        host="127.0.0.1",
        port=8787,
        cache_ttl_seconds=1,
        analytics_url="https://chatgpt.com/codex/cloud/settings/analytics#usage",
        manual_login_url="https://chatgpt.com/#usage",
        browser_app_name="Google Chrome",
        browser_debug_host="127.0.0.1",
        browser_debug_base_port=9222,
        playwright_channel="msedge",
        playwright_headless=True,
        scrape_timeout_ms=5000,
        mock_scraper_enabled=False,
        codex_auth_paths=[project_root / "missing-codex-auth.json"],
        codex_oauth_usage_url="https://chatgpt.com/backend-api/wham/usage",
        codex_cli_bin="missing-codex-for-tests",
        codex_cli_timeout_seconds=2.0,
        local_snapshot_connector_enabled=True,
    )
    settings.ensure_directories()
    settings.accounts_file.write_text(json.dumps({"accounts": []}) + "\n", encoding="utf-8")
    return settings


@pytest.fixture
def container(test_settings: Settings) -> ServiceContainer:
    container = ServiceContainer(test_settings)
    yield container
    container.shutdown()


@pytest.fixture
def app(container: ServiceContainer, test_settings: Settings):
    return create_app(settings=test_settings, container=container)
