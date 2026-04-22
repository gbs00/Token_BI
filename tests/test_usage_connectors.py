from __future__ import annotations

import json

import pytest

from app.models.account import AccountRecord, AccountStatus
from app.services.scraper_service import ScraperUnavailableError
from app.services.usage_connectors import (
    WebSessionConnector,
    ConnectorNotApplicableError,
    LocalCodexConnector,
    UsageConnectorManager,
    UsageConnectorResult,
)


class FailingConnector:
    name = "failing"
    source_type = "scraped"

    def fetch_usage(self, account):
        raise ScraperUnavailableError("connector failed")


class ReadyConnector:
    name = "ready"
    source_type = "scraped"

    def fetch_usage(self, account):
        return UsageConnectorResult(
            connector_name="ready",
            source_type="scraped",
            source_detail="network_response",
            payload={
                "session_remaining_pct": 90,
                "session_reset_at": "2026-04-22T03:00:00+08:00",
                "weekly_remaining_pct": 75,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
                "is_estimated": False,
            },
        )


class FakeBrowserWorkerService:
    def fetch_usage(self, account):
        return {
            "session_remaining_pct": 88,
            "session_reset_at": "2026-04-22T03:00:00+08:00",
            "weekly_remaining_pct": 71,
            "weekly_reset_at": "2026-04-28T00:00:00+08:00",
            "updated_at": "2026-04-21T23:00:00+08:00",
            "source_detail": "network_response",
            "is_estimated": False,
        }


def _build_account(test_settings) -> AccountRecord:
    return AccountRecord(
        account_id="acc_local",
        account_alias="guo****@gmail.com",
        masked_email="guo****@gmail.com",
        status=AccountStatus.ACTIVE,
        session_storage_path=str(test_settings.runtime_contexts_dir / "acc_local"),
    )


def test_local_codex_connector_reads_snapshot(test_settings) -> None:
    account = _build_account(test_settings)
    snapshot = test_settings.runtime_local_connector_dir / f"{account.account_id}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "session_remaining_pct": 82,
                "session_reset_at": "2026-04-22T03:00:00+08:00",
                "weekly_remaining_pct": 67,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )

    result = LocalCodexConnector(test_settings.runtime_local_connector_dir).fetch_usage(account)

    assert result.connector_name == "local_codex"
    assert result.source_type == "local_snapshot"
    assert result.payload["session_remaining_pct"] == 82


def test_local_codex_connector_skips_when_snapshot_missing(test_settings) -> None:
    account = _build_account(test_settings)
    connector = LocalCodexConnector(test_settings.runtime_local_connector_dir)

    with pytest.raises(ConnectorNotApplicableError):
        connector.fetch_usage(account)


def test_connector_manager_falls_back_after_failure(test_settings) -> None:
    account = _build_account(test_settings)
    manager = UsageConnectorManager([FailingConnector(), ReadyConnector()])

    result = manager.fetch_usage(account)

    assert result.connector_name == "ready"
    assert result.source_detail == "network_response"


def test_web_session_connector_uses_browser_worker(test_settings) -> None:
    account = _build_account(test_settings)
    connector = WebSessionConnector(FakeBrowserWorkerService())

    result = connector.fetch_usage(account)

    assert result.connector_name == "browser_worker"
    assert result.source_detail == "network_response"
    assert result.payload["session_remaining_pct"] == 88
