"""Read-only reset metadata must not compromise quota availability or account isolation."""
import json
from datetime import datetime, timezone

import pytest

from app.services.usage_connectors import (
    CodexOAuthConnector, CodexCliRpcConnector, ConnectorNetworkError,
    ConnectorTimeoutError, SessionExpiredError, normalize_usage_payload,
)
from test_usage_connectors import _build_account
from test_usage_sync_coordinator import _build_coordinator, _create_active_account, ControlledConnectorManager


def credit(key="one", expires="2030-01-01T12:00:00Z", **extra):
    return {"id": key, "status": "available", "reset_type": "codex_rate_limits", "expires_at": expires, **extra}


def oauth(tmp_path, get):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "test-token"}}))
    return CodexOAuthConnector(auth_paths=[auth], http_get=get)


def test_oauth_reads_details_with_same_token_and_short_deadline(tmp_path, test_settings):
    calls = []
    def get(url, headers, timeout):
        calls.append((url, headers, timeout))
        if url.endswith("/usage"):
            return {"weekly_remaining_pct": 53, "rate_limit_reset_credits": {"available_count": 3, "applicable_available_count": 0}}
        return {"available_count": 3, "credits": [credit(), credit("two", None)]}
    result = oauth(tmp_path, get).fetch_usage(_build_account(test_settings)).payload
    assert [url for url, _, _ in calls] == ["https://chatgpt.com/backend-api/wham/usage", "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"]
    assert calls[0][1] == calls[1][1]
    assert calls[1][2] == 2.0
    assert result["reset_credits"]["available_count"] == 3
    assert result["reset_credits"]["expires_at"] == [datetime(2030, 1, 1, 12, tzinfo=timezone.utc), None]
    assert result["windows"][0]["remaining_pct"] == 53
    assert "test-token" not in json.dumps(result, default=str)
    assert '"id"' not in json.dumps(result["reset_credits"], default=str)


@pytest.mark.parametrize("summary", [None, {}, {"available_count": 0}, {"available_count": -1}, {"available_count": True}])
def test_no_unnecessary_detail_request(tmp_path, test_settings, summary):
    calls = []
    def get(url, *_):
        calls.append(url)
        return {"weekly_remaining_pct": 53, "rate_limit_reset_credits": summary}
    result = oauth(tmp_path, get).fetch_usage(_build_account(test_settings)).payload
    assert len(calls) == 1
    assert result["reset_credits"] == ({"available_count": 0, "expires_at": []} if summary == {"available_count": 0} else None)


@pytest.mark.parametrize("failure", [ConnectorTimeoutError("slow"), ConnectorNetworkError("offline"), SessionExpiredError("unsupported")])
def test_optional_detail_failure_preserves_quota_and_count(tmp_path, test_settings, failure):
    def get(url, *_):
        if url.endswith("/usage"):
            return {"weekly_remaining_pct": 53, "rate_limit_reset_credits": {"available_count": 3}}
        raise failure
    result = oauth(tmp_path, get).fetch_usage(_build_account(test_settings)).payload
    assert result["windows"][0]["remaining_pct"] == 53
    assert result["reset_credits"] == {"available_count": 3, "expires_at": None}


@pytest.mark.parametrize("details", [[], None, {"available_count": "3"}, {"available_count": -1}])
def test_malformed_details_do_not_replace_valid_summary(tmp_path, test_settings, details):
    result = oauth(tmp_path, lambda url, *_: {"weekly_remaining_pct": 53, "rate_limit_reset_credits": {"available_count": 3}} if url.endswith("/usage") else details).fetch_usage(_build_account(test_settings)).payload
    assert result["reset_credits"] == {"available_count": 3, "expires_at": None}


def test_normalization_deduplicates_and_preserves_unknown_dates():
    raw = {"available_count": 5, "credits": [
        credit("late", "2030-02-01T00:00:00Z"), credit(), credit(),
        credit("consumed", status="redeemed"), credit("other", reset_type="other"),
        credit("bad", "garbage"), credit("naive", "2030-01-01T00:00:00"),
        credit("boolean", True), None,
    ]}
    result = normalize_usage_payload({"weekly_remaining_pct": 53, "rate_limit_reset_credits": raw}, "oauth", "test")["reset_credits"]
    assert result["available_count"] == 5
    assert result["expires_at"] == [datetime(2030, 1, 1, 12, tzinfo=timezone.utc), datetime(2030, 2, 1, tzinfo=timezone.utc), None, None, None]


@pytest.mark.parametrize("reset_type", [[], {}, None, 1])
def test_malformed_reset_type_does_not_fail_valid_quota(reset_type):
    result = normalize_usage_payload({
        "weekly_remaining_pct": 53,
        "rate_limit_reset_credits": {"available_count": 2, "credits": [
            credit("malformed", reset_type=reset_type), credit(),
        ]},
    }, "oauth", "test")
    assert result["windows"][0]["remaining_pct"] == 53
    assert result["reset_credits"] == {
        "available_count": 2,
        "expires_at": [datetime(2030, 1, 1, 12, tzinfo=timezone.utc)],
    }


def test_cli_reset_metadata_is_read_in_existing_account_verified_sequence(test_settings):
    calls = []
    def rpc(method, _):
        calls.append(method)
        if method == "account/read":
            return {"account": {"email": "test@example.com"}}
        return {"weekly_remaining_pct": 53, "rateLimitResetCredits": {"availableCount": 2, "credits": [{"id": "one", "status": "available", "resetType": "codexRateLimits", "expiresAt": 1893499200}]}}
    result = CodexCliRpcConnector(rpc_client=rpc).fetch_usage(_build_account(test_settings)).payload
    assert calls == ["account/read", "account/rateLimits/read", "account/read"]
    assert result["reset_credits"]["available_count"] == 2
    assert len(result["reset_credits"]["expires_at"]) == 1


def test_reset_snapshot_restores_and_clears_with_account(container):
    class Manager(ControlledConnectorManager):
        def fetch_usage(self, account):
            result = super().fetch_usage(account)
            result.payload["reset_credits"] = {"available_count": 3, "expires_at": ["2030-01-01T12:00:00Z"]}
            return result
    _create_active_account(container)
    coordinator, manager, store = _build_coordinator(container, Manager())
    ready = coordinator.refresh()
    assert ready.reset_credits.available_count == 3
    assert store.load(ready.account).reset_credits == ready.reset_credits
    assert coordinator.get_dashboard().reset_credits == ready.reset_credits
    assert manager.calls == 1
    assert store.load(ready.account.model_copy(update={"masked_email": "other@example.com"})) is None
    coordinator.disconnect()
    assert coordinator.get_dashboard().reset_credits is None
    assert not store.snapshot_path.exists()


def test_old_snapshot_without_reset_field_remains_readable(container):
    _create_active_account(container)
    coordinator, _, store = _build_coordinator(container)
    ready = coordinator.refresh()
    raw = json.loads(store.snapshot_path.read_text())
    raw.pop("reset_credits")
    store.snapshot_path.write_text(json.dumps(raw))
    restored = store.load(ready.account)
    assert restored.metrics == ready.metrics
    assert restored.reset_credits is None
