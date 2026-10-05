"""Read-only reset metadata must not compromise quota availability or account isolation."""
import json
from datetime import datetime, timedelta, timezone

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
    assert calls[1][2] == 5.0
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
def test_optional_detail_failure_preserves_quota_and_count(tmp_path, test_settings, failure, caplog):
    def get(url, *_):
        if url.endswith("/usage"):
            return {"weekly_remaining_pct": 53, "rate_limit_reset_credits": {"available_count": 3}}
        raise failure
    result = oauth(tmp_path, get).fetch_usage(_build_account(test_settings)).payload
    assert result["windows"][0]["remaining_pct"] == 53
    assert result["reset_credits"] == {"available_count": 3, "expires_at": None}
    assert f"reset_details_unavailable error_type={type(failure).__name__}" in caplog.text
    assert "test-token" not in caplog.text
    assert str(failure) not in caplog.text


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


class ResetManager(ControlledConnectorManager):
    def __init__(self):
        super().__init__()
        self.resets = {"available_count": 2, "expires_at": ["2030-01-01T12:00:00Z", "2030-01-02T12:00:00Z"]}
        self.key = "a" * 64

    def fetch_usage(self, account):
        result = super().fetch_usage(account)
        result.payload.update(reset_credits=self.resets, account_identity_key=self.key)
        return result


def test_missing_reset_details_retain_original_timestamp_across_restart(container):
    _create_active_account(container)
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    manager = ResetManager()
    coordinator, _, store = _build_coordinator(container, manager, now=lambda: now[0])
    ready = coordinator.refresh()
    manager.resets = {"available_count": 2, "expires_at": None}
    now[0] += timedelta(minutes=3)
    stale = coordinator.refresh()
    assert stale.state.value == "ready"
    assert stale.reset_credits.details_stale is True
    assert stale.reset_credits.expires_at == ready.reset_credits.expires_at
    assert stale.reset_credits.details_updated_at == ready.reset_credits.details_updated_at
    assert stale.summary.last_success_at == now[0]
    assert store.load(stale.account).reset_credits == stale.reset_credits

    restarted, _, _ = _build_coordinator(container, manager, now=lambda: now[0])
    now[0] += timedelta(minutes=3)
    assert restarted.refresh().reset_credits == stale.reset_credits
    now[0] += timedelta(minutes=10)
    expired = restarted.refresh().reset_credits
    assert expired.expires_at is None
    assert expired.details_updated_at is None
    assert expired.details_stale is False


@pytest.mark.parametrize("change", ["count", "zero", "unsupported", "identity", "unverified", "expired", "logout", "clock_back"])
def test_reset_details_never_cross_invalid_boundaries(container, change):
    _create_active_account(container)
    now = [datetime(2030, 1, 1, tzinfo=timezone.utc)]
    manager = ResetManager()
    if change == "unverified":
        manager.key = None
    elif change == "expired":
        manager.resets["expires_at"][0] = "2030-01-01T00:01:00Z"
    coordinator, _, _ = _build_coordinator(container, manager, now=lambda: now[0])
    coordinator.refresh()
    manager.resets = {"available_count": 2, "expires_at": None}
    now[0] += timedelta(minutes=3)
    if change == "count":
        manager.resets["available_count"] = 3
    elif change == "zero":
        manager.resets = {"available_count": 0, "expires_at": []}
    elif change == "unsupported":
        manager.resets = None
    elif change == "identity":
        manager.key = "b" * 64
    elif change == "clock_back":
        now[0] -= timedelta(minutes=4)
    elif change == "logout":
        coordinator.disconnect()
        assert coordinator.get_dashboard().reset_credits is None
        coordinator.resume()
    resets = coordinator.refresh().reset_credits
    assert resets is None or not resets.expires_at
    assert resets is None or not resets.details_stale


def test_partial_fresh_details_replace_old_rows_without_merging(container):
    _create_active_account(container)
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    manager = ResetManager()
    coordinator, _, _ = _build_coordinator(container, manager, now=lambda: now)
    coordinator.refresh()
    manager.resets = {"available_count": 2, "expires_at": ["2030-01-03T12:00:00Z", None]}
    resets = coordinator.refresh().reset_credits
    assert resets.expires_at == [datetime(2030, 1, 3, 12, tzinfo=timezone.utc), None]
    assert resets.details_stale is False
