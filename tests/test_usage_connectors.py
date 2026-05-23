from __future__ import annotations

import json
import base64
from datetime import datetime

import pytest

from app.models.account import AccountRecord, AccountStatus
from app.services.scraper_service import ScraperUnavailableError
from app.services.usage_connectors import (
    CodexCliRpcConnector,
    CodexOAuthConnector,
    ConnectorNotApplicableError,
    LocalCodexConnector,
    UsageConnectorManager,
    UsageConnectorResult,
    WebSessionConnector,
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


class SensitiveFailingConnector:
    name = "sensitive_failing"
    source_type = "oauth"

    def fetch_usage(self, account):
        raise ScraperUnavailableError(
            "access_token=secret-token Authorization: Bearer another-token "
            "cookie=session-id someone.long@example.com"
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


def _build_unsigned_jwt(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}

    def encode(segment: dict) -> str:
        raw = json.dumps(segment, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode(header)}.{encode(payload)}.signature"


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
    assert result.payload["windows"][0]["remaining_pct"] == 82


def test_local_codex_connector_accepts_weekly_only_snapshot(test_settings) -> None:
    account = _build_account(test_settings)
    snapshot = test_settings.runtime_local_connector_dir / f"{account.account_id}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "weekly_remaining_pct": 67,
                "weekly_reset_at": "2026-04-28T00:00:00+08:00",
                "updated_at": "2026-04-21T23:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )

    result = LocalCodexConnector(test_settings.runtime_local_connector_dir).fetch_usage(account)

    assert result.connector_name == "local_codex"
    assert [window["display_name"] for window in result.payload["windows"]] == ["Weekly"]
    assert result.payload["windows"][0]["remaining_pct"] == 67


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


def test_connector_manager_redacts_sensitive_error_details(test_settings) -> None:
    account = _build_account(test_settings)
    manager = UsageConnectorManager([SensitiveFailingConnector()])

    with pytest.raises(ScraperUnavailableError):
        manager.fetch_usage(account)

    message = manager.last_connector_errors[0]["message"]
    assert "secret-token" not in message
    assert "another-token" not in message
    assert "session-id" not in message
    assert "someone.long@example.com" not in message
    assert "some****@example.com" in message


def test_oauth_connector_reads_codex_auth_and_normalizes_official_windows(test_settings) -> None:
    account = _build_account(test_settings)
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": "secret-token"}}),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_http_get(url: str, headers: dict[str, str], timeout: float) -> dict:
        calls.append({"url": url, "headers": headers, "timeout": timeout})
        return {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 20,
                    "reset_at": "2026-05-23T18:00:00+08:00",
                    "limit_window_seconds": 18000,
                }
            }
        }

    connector = CodexOAuthConnector(
        auth_paths=[auth_path],
        usage_url="https://chatgpt.com/backend-api/wham/usage",
        http_get=fake_http_get,
        timeout_seconds=2.0,
    )

    result = connector.fetch_usage(account)

    assert result.connector_name == "codex_oauth"
    assert result.source_type == "oauth"
    assert result.source_detail == "oauth_usage_api"
    assert result.payload["windows"][0]["display_name"] == "5h window"
    assert result.payload["windows"][0]["remaining_pct"] == 80
    assert isinstance(result.payload["windows"][0]["reset_at"], datetime)
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    assert "secret-token" not in json.dumps(result.payload, default=str)


def test_oauth_connector_syncs_masked_identity_from_codex_profile_claim(test_settings) -> None:
    account = _build_account(test_settings)
    auth_path = test_settings.config_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": _build_unsigned_jwt(
                        {
                            "exp": 4102444800,
                            "https://api.openai.com/profile": {
                                "email": "someone.long@example.com",
                                "email_verified": True,
                            },
                        }
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    connector = CodexOAuthConnector(
        auth_paths=[auth_path],
        usage_url="https://chatgpt.com/backend-api/wham/usage",
        http_get=lambda *_args, **_kwargs: {
            "rate_limit": {
                "primary_window": {
                    "remaining_pct": 73,
                    "reset_at": "2026-05-23T18:00:00+08:00",
                    "limit_window_seconds": 18000,
                }
            }
        },
        timeout_seconds=2.0,
    )

    result = connector.fetch_usage(account)

    assert result.payload["account_masked_email"] == "some****@example.com"


def test_oauth_connector_skips_when_auth_file_missing(test_settings) -> None:
    account = _build_account(test_settings)
    connector = CodexOAuthConnector(
        auth_paths=[test_settings.config_dir / "missing-auth.json"],
        usage_url="https://chatgpt.com/backend-api/wham/usage",
        http_get=lambda *_args, **_kwargs: {},
        timeout_seconds=2.0,
    )

    with pytest.raises(ConnectorNotApplicableError):
        connector.fetch_usage(account)


def test_cli_rpc_connector_reads_account_and_rate_limit_windows(test_settings) -> None:
    account = _build_account(test_settings)
    seen_methods: list[str] = []

    def fake_rpc(method: str, params):
        seen_methods.append(method)
        if method == "account/read":
            return {
                "account": {
                    "type": "chatgpt",
                    "email": "someone.long@example.com",
                    "planType": "pro",
                },
                "requiresOpenaiAuth": False,
            }
        if method == "account/rateLimits/read":
            return {
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitId": "codex",
                        "limitName": "Codex",
                        "primary": {
                            "usedPercent": 12,
                            "resetsAt": 1776843664,
                            "windowDurationMins": 300,
                        },
                        "secondary": {
                            "usedPercent": 4,
                            "resetsAt": 1777430464,
                            "windowDurationMins": 10080,
                        },
                    }
                },
                "rateLimits": None,
            }
        raise AssertionError(method)

    connector = CodexCliRpcConnector(
        codex_bin="codex",
        rpc_client=fake_rpc,
        timeout_seconds=2.0,
    )

    result = connector.fetch_usage(account)

    assert seen_methods == ["account/read", "account/rateLimits/read"]
    assert result.connector_name == "codex_cli_rpc"
    assert result.source_type == "cli_rpc"
    assert result.payload["account_masked_email"] == "some****@example.com"
    assert [window["remaining_pct"] for window in result.payload["windows"]] == [88, 96]
    assert [window["window_minutes"] for window in result.payload["windows"]] == [300, 10080]


def test_web_session_connector_uses_browser_worker(test_settings) -> None:
    account = _build_account(test_settings)
    connector = WebSessionConnector(FakeBrowserWorkerService())

    result = connector.fetch_usage(account)

    assert result.connector_name == "browser_worker"
    assert result.source_detail == "network_response"
    assert result.source_type == "web_session"
    assert result.payload["windows"][0]["remaining_pct"] == 88
