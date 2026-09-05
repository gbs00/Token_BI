from __future__ import annotations

import base64
import asyncio
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol
import httpx

from app.models.account import AccountRecord, identity_key
from app.services.browser_worker_service import BrowserWorkerService, LiveSessionRequiredError
from app.services.scraper_service import (
    AnalyticsPageChangedError,
    ScraperUnavailableError,
    SessionExpiredError,
)


class ConnectorNotApplicableError(ScraperUnavailableError):
    pass


class ConnectorRateLimitedError(ScraperUnavailableError):
    def __init__(self, message: str, retry_after_seconds: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ConnectorNetworkError(ScraperUnavailableError):
    def __init__(self, message: str, immediate_retry: bool = False) -> None:
        super().__init__(message)
        self.immediate_retry = immediate_retry


class ConnectorTimeoutError(ScraperUnavailableError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.immediate_retry = True


class ConnectorFailureCategory(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    AUTH_REQUIRED = "auth_required"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SOURCE_CHANGED = "source_changed"
    WEB_SESSION_INACTIVE = "web_session_inactive"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class ConnectorFailure:
    connector_name: str
    category: ConnectorFailureCategory
    error_type: str
    message: str
    retry_after_seconds: Optional[float] = None
    immediate_retry: bool = False


class ConnectorChainError(ScraperUnavailableError):
    def __init__(
        self,
        primary_failure: ConnectorFailure,
        failures: Iterable[ConnectorFailure],
    ) -> None:
        super().__init__(primary_failure.message)
        self.primary_failure = primary_failure
        self.failures = tuple(failures)

    @property
    def category(self) -> ConnectorFailureCategory:
        return self.primary_failure.category

    @property
    def retry_after_seconds(self) -> Optional[float]:
        return self.primary_failure.retry_after_seconds

    @property
    def immediate_retry(self) -> bool:
        return self.primary_failure.immediate_retry


@dataclass(frozen=True)
class UsageConnectorResult:
    connector_name: str
    source_type: str
    source_detail: str
    payload: dict


class UsageConnector(Protocol):
    name: str
    source_type: str

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        ...


HttpGet = Callable[[str, dict[str, str], float], dict]
RpcClient = Callable[[str, Any], dict]


def default_codex_auth_paths() -> list[Path]:
    paths: list[Path] = []
    codex_home = os.getenv("CODEX_HOME")
    if codex_home:
        paths.append(Path(codex_home).expanduser() / "auth.json")
    paths.append(Path.home() / ".codex" / "auth.json")
    return paths


class CodexOAuthConnector:
    name = "codex_oauth"
    source_type = "oauth"

    def __init__(
        self,
        auth_paths: Optional[Iterable[Path]] = None,
        usage_url: str = "https://chatgpt.com/backend-api/wham/usage",
        http_get: Optional[HttpGet] = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self._auth_paths = list(auth_paths or default_codex_auth_paths())
        self._usage_url = usage_url
        self._http_get = http_get or self._default_http_get
        self._timeout_seconds = timeout_seconds

    def auth_available(self) -> bool:
        try:
            access_token, _ = self._read_auth_tokens()
        except ScraperUnavailableError:
            return False
        return not self._token_expired(access_token)

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        access_token, id_token = self._read_auth_tokens()
        if self._token_expired(access_token):
            raise SessionExpiredError("Codex local login expired. Please complete Codex login again.")

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        payload = self._http_get(self._usage_url, headers, self._timeout_seconds)
        normalized = normalize_usage_payload(
            payload,
            source_type=self.source_type,
            source_detail="oauth_usage_api",
        )
        account_identity = self._extract_account_identity(id_token) or self._extract_account_identity(
            access_token
        )
        if account_identity:
            normalized["account_masked_email"] = account_identity
        email = self._extract_email(id_token) or self._extract_email(access_token)
        if email:
            normalized["account_identity_key"] = identity_key(email)
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail="oauth_usage_api",
            payload=normalized,
        )

    def _read_auth_tokens(self) -> tuple[str, Optional[str]]:
        unreadable_paths: list[Path] = []
        for path in self._auth_paths:
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                unreadable_paths.append(path)
                continue

            tokens = payload.get("tokens")
            if not isinstance(tokens, dict):
                continue
            access_token = tokens.get("access_token") or tokens.get("accessToken")
            if isinstance(access_token, str) and access_token.strip():
                id_token = tokens.get("id_token") or tokens.get("idToken")
                normalized_id_token = (
                    id_token.strip() if isinstance(id_token, str) and id_token.strip() else None
                )
                return access_token.strip(), normalized_id_token

        if unreadable_paths:
            raise ScraperUnavailableError("Codex auth file is unreadable.")
        raise ConnectorNotApplicableError("Codex local auth is not available.")

    def _token_expired(self, token: str) -> bool:
        payload = self._decode_jwt_payload(token)
        if payload is None:
            return False
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            return False
        return datetime.now(timezone.utc).timestamp() >= float(exp) - 30

    def _extract_account_identity(self, token: str) -> Optional[str]:
        email = self._extract_email(token)
        return mask_identity(email) if email else None

    def _extract_email(self, token: Optional[str]) -> Optional[str]:
        payload = self._decode_jwt_payload(token)
        if payload is None:
            return None
        profile = payload.get("https://api.openai.com/profile")
        if isinstance(profile, dict):
            email = profile.get("email")
            if isinstance(email, str) and email.strip():
                return email.strip()
        email = payload.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip()
        return None

    def _decode_jwt_payload(self, token: str) -> Optional[dict]:
        try:
            payload_segment = token.split(".")[1]
            padding = "=" * (-len(payload_segment) % 4)
            decoded = base64.urlsafe_b64decode(payload_segment + padding)
            payload = json.loads(decoded)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _default_http_get(self, url: str, headers: dict[str, str], timeout: float) -> dict:
        async def read_response() -> bytes:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 4 * 1024 * 1024:
                            raise AnalyticsPageChangedError("额度响应超过大小限制。")
                        chunks.append(chunk)
                    return b"".join(chunks)

        async def fetch_with_deadline() -> bytes:
            # 总截止时间包含连接、响应头和响应体，而非仅限制相邻字节的间隔。
            return await asyncio.wait_for(read_response(), timeout=timeout)

        try:
            raw = asyncio.run(fetch_with_deadline())
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                raise SessionExpiredError("Codex login is not authorized for usage data.") from exc
            if code == 429:
                retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))
                raise ConnectorRateLimitedError(
                    "Codex usage endpoint is rate limited.",
                    retry_after_seconds=retry_after,
                ) from exc
            if code >= 500:
                raise ConnectorNetworkError(
                    "Codex usage endpoint is temporarily unavailable.",
                    immediate_retry=True,
                ) from exc
            raise ScraperUnavailableError(f"Codex usage endpoint returned HTTP {code}.") from exc
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise ConnectorTimeoutError("Codex usage endpoint timed out.") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise ConnectorNetworkError("Unable to reach Codex usage endpoint.") from exc

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AnalyticsPageChangedError("Codex usage endpoint returned an unsupported payload.") from exc


class CodexCliRpcConnector:
    name = "codex_cli_rpc"
    source_type = "cli_rpc"

    def __init__(
        self,
        codex_bin: str = "codex",
        rpc_client: Optional[RpcClient] = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self._codex_bin = codex_bin
        self._rpc_client = rpc_client
        self._timeout_seconds = timeout_seconds

    def cli_available(self) -> bool:
        return self._rpc_client is not None or shutil.which(self._codex_bin) is not None

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        if not self.cli_available():
            raise ConnectorNotApplicableError("Codex CLI is not installed.")

        deadline = time.monotonic() + self._timeout_seconds
        requests = [
            ("account/read", {"refreshToken": False}),
            ("account/rateLimits/read", None),
            ("account/read", {"refreshToken": False}),
        ]
        if self._rpc_client is not None:
            responses = [self._rpc_client(method, params) for method, params in requests]
        else:
            responses = self._rpc_sequence(requests, deadline)
        account_payload, rate_limit_payload, verified_account = responses
        account_identity = self._extract_account_identity(account_payload)
        if account_payload.get("requiresOpenaiAuth") and account_payload.get("account") is None:
            raise SessionExpiredError("Codex CLI is not signed in. Please complete Codex login.")

        if account_payload.get("account") != verified_account.get("account"):
            raise ConnectorNetworkError("CLI 账号在采集期间发生变化，正在重新读取。", immediate_retry=True)
        normalized = normalize_usage_payload(
            rate_limit_payload,
            source_type=self.source_type,
            source_detail="cli_rate_limits",
        )
        if account_identity:
            normalized["account_masked_email"] = account_identity
            normalized["account_identity_key"] = identity_key(account_payload["account"]["email"])
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail="cli_rate_limits",
            payload=normalized,
        )

    def _rpc_sequence(self, requests: list[tuple[str, Any]], deadline: Optional[float] = None) -> list[dict]:
        deadline = deadline if deadline is not None else time.monotonic() + self._timeout_seconds
        if time.monotonic() >= deadline:
            raise ConnectorTimeoutError("Codex CLI 采集超时。")
        if shutil.which(self._codex_bin) is None:
            raise ConnectorNotApplicableError("Codex CLI is not installed.")

        try:
            process = subprocess.Popen(
                [self._codex_bin, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise ScraperUnavailableError("Codex app-server is not available.") from exc

        try:
            self._write_jsonrpc(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "token-bi", "version": "1.1.3"},
                        "capabilities": {"experimentalApi": True},
                    },
                },
            )
            initialized = self._read_jsonrpc_response(process, request_id=1, deadline=deadline)
            if "error" in initialized:
                raise ScraperUnavailableError("Codex app-server 初始化失败。")
            self._write_jsonrpc(process, {"jsonrpc": "2.0", "method": "initialized"})
            results = []
            for request_id, (method, params) in enumerate(requests, start=2):
                self._write_jsonrpc(process, {
                    "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
                })
                response = self._read_jsonrpc_response(process, request_id=request_id, deadline=deadline)
                if "error" in response:
                    raise ScraperUnavailableError("Codex app-server returned an RPC error.")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise AnalyticsPageChangedError("Codex app-server returned an unsupported payload.")
                if method == "account/read" and result.get("requiresOpenaiAuth") and result.get("account") is None:
                    raise SessionExpiredError("Codex CLI is not signed in. Please complete Codex login.")
                results.append(result)
            return results
        finally:
            self._stop_rpc_process(process)

    def _write_jsonrpc(self, process: subprocess.Popen, request: dict) -> None:
        if process.stdin is None:
            raise ScraperUnavailableError("Codex app-server RPC is not writable.")
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise ScraperUnavailableError("Codex app-server RPC is not writable.") from exc

    def _read_jsonrpc_response(
        self, process: subprocess.Popen, request_id: int, deadline: Optional[float] = None,
    ) -> dict:
        if process.stdout is None:
            raise ScraperUnavailableError("Codex app-server RPC is not readable.")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ)
        deadline = deadline if deadline is not None else time.monotonic() + self._timeout_seconds
        buffer = b""
        try:
            while time.monotonic() < deadline and selector.get_map():
                events = selector.select(timeout=min(0.1, max(0, deadline - time.monotonic())))
                for key, _ in events:
                    # 按可读字节分帧，不能让 readline 等待半行而越过截止时间。
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stderr:
                        continue
                    buffer += chunk
                    if len(buffer) > 4 * 1024 * 1024:
                        raise AnalyticsPageChangedError("Codex RPC 响应超过大小限制。")
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            payload = json.loads(line)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue
                        if isinstance(payload, dict) and payload.get("id") == request_id:
                            if time.monotonic() >= deadline:
                                raise ConnectorTimeoutError("Codex app-server RPC 超时。")
                            return payload
        finally:
            selector.close()
        raise ConnectorTimeoutError("Codex app-server RPC timed out.")

    def _stop_rpc_process(self, process: subprocess.Popen) -> None:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def _extract_account_identity(self, payload: dict) -> Optional[str]:
        account = payload.get("account")
        if not isinstance(account, dict):
            return None
        email = account.get("email")
        if isinstance(email, str) and email.strip():
            return mask_identity(email)
        return None


class LocalCodexConnector:
    name = "local_codex"
    source_type = "local_snapshot"

    def __init__(self, snapshot_dir: Path) -> None:
        self._snapshot_dir = snapshot_dir

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        snapshot_path = self._snapshot_dir / f"{account.account_id}.json"
        if not snapshot_path.exists():
            raise ConnectorNotApplicableError(
                "Local Codex connector is not configured for this account."
            )

        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ScraperUnavailableError(
                f"Invalid local connector snapshot: {snapshot_path.name}"
            ) from exc

        normalized = normalize_usage_payload(
            payload,
            source_type=self.source_type,
            source_detail="local_snapshot_json",
        )
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail="local_snapshot_json",
            payload=normalized,
        )


class WebSessionConnector:
    name = "browser_worker"
    source_type = "web_session"

    def __init__(self, browser_worker_service: BrowserWorkerService) -> None:
        self._browser_worker_service = browser_worker_service

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        payload = self._browser_worker_service.fetch_usage(account)
        source_detail = str(payload.get("source_detail", "live_browser_unknown"))
        source_type = "dom_fallback" if source_detail == "dom_fallback" else self.source_type
        normalized = normalize_usage_payload(
            payload,
            source_type=source_type,
            source_detail=source_detail,
        )
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=source_type,
            source_detail=source_detail,
            payload=normalized,
        )


class UsageConnectorManager:
    def __init__(self, connectors: Iterable[UsageConnector]) -> None:
        self._connectors = list(connectors)
        self.last_connector_errors: list[dict[str, str]] = []

    @property
    def connectors(self) -> list[UsageConnector]:
        return list(self._connectors)

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        failures: list[ConnectorFailure] = []
        for connector in self._connectors:
            try:
                result = connector.fetch_usage(account)
                self.last_connector_errors = self._serialize_failures(failures)
                return result
            except ScraperUnavailableError as exc:
                failures.append(self._to_failure(connector.name, exc))
                continue
            except Exception as exc:
                failures.append(
                    ConnectorFailure(
                        connector_name=connector.name,
                        category=ConnectorFailureCategory.INTERNAL_ERROR,
                        error_type=exc.__class__.__name__,
                        message="Usage connector failed unexpectedly.",
                    )
                )
                continue

        self.last_connector_errors = self._serialize_failures(failures)
        if not failures:
            failures.append(
                ConnectorFailure(
                    connector_name="connector_manager",
                    category=ConnectorFailureCategory.INTERNAL_ERROR,
                    error_type="NoConnectorError",
                    message="No usage connector is configured.",
                )
            )
        raise ConnectorChainError(self._select_primary_failure(failures), failures)

    def _to_failure(self, connector_name: str, exc: ScraperUnavailableError) -> ConnectorFailure:
        category = ConnectorFailureCategory.INTERNAL_ERROR
        if isinstance(exc, ConnectorNotApplicableError):
            category = ConnectorFailureCategory.NOT_APPLICABLE
        elif isinstance(exc, SessionExpiredError):
            category = ConnectorFailureCategory.AUTH_REQUIRED
        elif isinstance(exc, ConnectorRateLimitedError):
            category = ConnectorFailureCategory.RATE_LIMITED
        elif isinstance(exc, AnalyticsPageChangedError):
            category = ConnectorFailureCategory.SOURCE_CHANGED
        elif isinstance(exc, ConnectorTimeoutError):
            category = ConnectorFailureCategory.TIMEOUT
        elif isinstance(exc, ConnectorNetworkError):
            category = ConnectorFailureCategory.NETWORK_ERROR
        elif isinstance(exc, LiveSessionRequiredError):
            category = ConnectorFailureCategory.WEB_SESSION_INACTIVE

        return ConnectorFailure(
            connector_name=connector_name,
            category=category,
            error_type=exc.__class__.__name__,
            message=redact_sensitive_text(str(exc)),
            retry_after_seconds=getattr(exc, "retry_after_seconds", None),
            immediate_retry=bool(getattr(exc, "immediate_retry", False)),
        )

    def _select_primary_failure(self, failures: list[ConnectorFailure]) -> ConnectorFailure:
        primary_names = {"codex_oauth", "codex_cli_rpc"}
        primary_failures = [item for item in failures if item.connector_name in primary_names]
        candidates = primary_failures or [
            item
            for item in failures
            if item.category != ConnectorFailureCategory.WEB_SESSION_INACTIVE
        ]
        candidates = candidates or failures

        # 高优数据源的真实错误优先，Web Session 仅作为最后兜底，不能覆盖根因。
        for category in (
            ConnectorFailureCategory.RATE_LIMITED,
            ConnectorFailureCategory.SOURCE_CHANGED,
            ConnectorFailureCategory.TIMEOUT,
            ConnectorFailureCategory.NETWORK_ERROR,
            ConnectorFailureCategory.INTERNAL_ERROR,
            ConnectorFailureCategory.AUTH_REQUIRED,
            ConnectorFailureCategory.WEB_SESSION_INACTIVE,
            ConnectorFailureCategory.NOT_APPLICABLE,
        ):
            matching = [item for item in candidates if item.category == category]
            if matching:
                return matching[0]
        return failures[0]

    def _serialize_failures(self, failures: list[ConnectorFailure]) -> list[dict[str, str]]:
        return [
            {
                "connector_name": item.connector_name,
                "category": item.category.value,
                "error_type": item.error_type,
                "message": item.message,
            }
            for item in failures
        ]


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (TypeError, ValueError):
        return None


def normalize_usage_payload(payload: dict, source_type: str, source_detail: str) -> dict:
    windows = _extract_windows(payload, source_type=source_type, source_detail=source_detail)
    if not windows:
        raise AnalyticsPageChangedError("Usage payload is missing official usage windows.")

    normalized: dict[str, Any] = {
        "updated_at": _coerce_datetime(payload.get("updated_at")) or datetime.now().astimezone(),
        "is_estimated": bool(payload.get("is_estimated", False)),
        "windows": windows,
    }
    account_identity = payload.get("account_masked_email")
    if isinstance(account_identity, str) and account_identity.strip():
        normalized["account_masked_email"] = account_identity.strip()
    if isinstance(payload.get("account_identity_key"), str):
        normalized["account_identity_key"] = payload["account_identity_key"]
    return normalized


def _extract_windows(payload: dict, source_type: str, source_detail: str) -> list[dict]:
    if isinstance(payload.get("windows"), list):
        return [
            window
            for window in (
                _normalize_window(
                    item,
                    source_type=source_type,
                    source_detail=source_detail,
                    default_display_name=None,
                    metric_type=item.get("metric_type") if isinstance(item, dict) else None,
                )
                for item in payload["windows"]
                if isinstance(item, dict)
            )
            if window is not None
        ]

    rate_limit = payload.get("rate_limit")
    if isinstance(rate_limit, dict):
        return _extract_wham_rate_limit_windows(rate_limit, source_type, source_detail)

    if "rateLimits" in payload or "rateLimitsByLimitId" in payload:
        return _extract_cli_rate_limit_windows(payload, source_type, source_detail)

    return _extract_legacy_windows(payload, source_type, source_detail)


def _extract_wham_rate_limit_windows(rate_limit: dict, source_type: str, source_detail: str) -> list[dict]:
    windows: list[dict] = []
    for role, key in (("primary", "primary_window"), ("secondary", "secondary_window")):
        raw_window = rate_limit.get(key)
        if not isinstance(raw_window, dict):
            continue
        window = _normalize_window(
            raw_window,
            source_type=source_type,
            source_detail=source_detail,
            default_display_name=None,
            role=role,
        )
        if window is not None:
            windows.append(window)
    return windows


def _extract_cli_rate_limit_windows(payload: dict, source_type: str, source_detail: str) -> list[dict]:
    snapshots: list[tuple[str, dict]] = []
    by_limit_id = payload.get("rateLimitsByLimitId")
    if isinstance(by_limit_id, dict) and by_limit_id:
        if isinstance(by_limit_id.get("codex"), dict):
            snapshots.append(("codex", by_limit_id["codex"]))
        else:
            snapshots.extend((str(key), value) for key, value in by_limit_id.items() if isinstance(value, dict))
    elif isinstance(payload.get("rateLimits"), dict):
        snapshot = payload["rateLimits"]
        snapshots.append((str(snapshot.get("limitId") or "rateLimits"), snapshot))

    windows: list[dict] = []
    for limit_id, snapshot in snapshots:
        limit_name = _first_string(snapshot, ("limitName", "limit_name")) or limit_id
        for role in ("primary", "secondary"):
            raw_window = snapshot.get(role)
            if not isinstance(raw_window, dict):
                continue
            window = _normalize_window(
                raw_window,
                source_type=source_type,
                source_detail=source_detail,
                default_display_name=None,
                role=role,
                limit_id=limit_id,
                limit_name=limit_name,
            )
            if window is not None:
                windows.append(window)
    return windows


def _extract_legacy_windows(payload: dict, source_type: str, source_detail: str) -> list[dict]:
    windows: list[dict] = []
    legacy_specs = (
        ("session", "5h Session", "session_remaining_pct", "session_reset_at"),
        ("weekly", "Weekly", "weekly_remaining_pct", "weekly_reset_at"),
    )
    for metric_type, display_name, remaining_key, reset_key in legacy_specs:
        if remaining_key not in payload and reset_key not in payload:
            continue
        raw_window = {
            "remaining_pct": payload.get(remaining_key),
            "reset_at": payload.get(reset_key),
            "display_name": display_name,
        }
        window = _normalize_window(
            raw_window,
            source_type=source_type,
            source_detail=source_detail,
            default_display_name=display_name,
            metric_type=metric_type,
        )
        if window is not None:
            windows.append(window)
    return windows


def _normalize_window(
    raw_window: dict,
    source_type: str,
    source_detail: str,
    default_display_name: Optional[str],
    metric_type: Optional[str] = None,
    role: Optional[str] = None,
    limit_id: Optional[str] = None,
    limit_name: Optional[str] = None,
) -> Optional[dict]:
    remaining_pct = _remaining_pct(raw_window)
    reset_at = _coerce_datetime(
        _first_present(raw_window, ("reset_at", "resetAt", "resetsAt"))
    )
    window_seconds = _window_seconds(raw_window)
    window_minutes = _window_minutes(raw_window, window_seconds)
    display_name = (
        _first_string(raw_window, ("display_name", "displayName", "name", "label", "title"))
        or default_display_name
        or _duration_display_name(window_seconds=window_seconds, window_minutes=window_minutes, limit_name=limit_name)
        or (f"{role.title()} window" if role else None)
        or "Usage window"
    )

    if remaining_pct is None and reset_at is None and window_seconds is None and window_minutes is None:
        return None

    return {
        "raw_window": raw_window,
        "display_name": display_name,
        "metric_type": metric_type,
        "remaining_pct": remaining_pct,
        "reset_at": reset_at,
        "window_seconds": window_seconds,
        "window_minutes": window_minutes,
        "source_type": source_type,
        "source_detail": source_detail,
        "limit_id": limit_id,
        "role": role,
    }


def _remaining_pct(raw_window: dict) -> Optional[int]:
    remaining = _first_present(
        raw_window,
        ("remaining_pct", "remainingPercent", "remaining_percent"),
    )
    if remaining is not None:
        return _clamp_pct(remaining)

    used = _first_present(raw_window, ("used_percent", "usedPercent", "used_percentage"))
    if used is not None:
        try:
            return _clamp_pct(100 - float(used))
        except (TypeError, ValueError, OverflowError) as exc:
            raise AnalyticsPageChangedError("Usage percentage has an unsupported value.") from exc
    return None


def _window_seconds(raw_window: dict) -> Optional[int]:
    value = _first_present(
        raw_window,
        ("window_seconds", "windowSeconds", "limit_window_seconds", "limitWindowSeconds"),
    )
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnalyticsPageChangedError("Usage window duration has an unsupported value.") from exc


def _window_minutes(raw_window: dict, window_seconds: Optional[int]) -> Optional[int]:
    value = _first_present(
        raw_window,
        ("window_minutes", "windowMinutes", "windowDurationMins"),
    )
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise AnalyticsPageChangedError("Usage window duration has an unsupported value.") from exc
    if window_seconds is not None:
        return max(1, int(window_seconds / 60))
    return None


def _duration_display_name(
    window_seconds: Optional[int],
    window_minutes: Optional[int],
    limit_name: Optional[str],
) -> Optional[str]:
    minutes = window_minutes
    if minutes is None and window_seconds is not None:
        minutes = max(1, int(window_seconds / 60))
    if minutes is None:
        return None

    if minutes % 1440 == 0:
        duration = f"{minutes // 1440}d window"
    elif minutes % 60 == 0:
        duration = f"{minutes // 60}h window"
    else:
        duration = f"{minutes}m window"
    return f"{limit_name} {duration}" if limit_name else duration


def _first_present(payload: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _first_string(payload: dict, keys: tuple[str, ...]) -> Optional[str]:
    value = _first_present(payload, keys)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
        except (OverflowError, OSError, ValueError) as exc:
            raise AnalyticsPageChangedError("Usage reset time has an unsupported value.") from exc
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AnalyticsPageChangedError("Usage reset time has an unsupported value.") from exc
    raise AnalyticsPageChangedError(f"Unsupported datetime payload: {type(value).__name__}")


def _clamp_pct(value: Any) -> int:
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AnalyticsPageChangedError("Usage percentage has an unsupported value.") from exc
    return max(0, min(100, pct))


def mask_identity(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value or "").strip()
    if not normalized:
        return ""
    if "@" not in normalized:
        return normalized if len(normalized) <= 4 else f"{normalized[:4]}..."
    local, _, domain = normalized.partition("@")
    if not local or not domain:
        return normalized if len(normalized) <= 4 else f"{normalized[:4]}..."
    keep = min(4, max(1, len(local)))
    return f"{local[:keep]}****@{domain}"


def redact_sensitive_text(value: str) -> str:
    redacted = value or ""
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*)bearer\s+[A-Za-z0-9._~+/=-]+",
        r"\1Bearer [redacted]",
        redacted,
    )
    redacted = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", redacted)
    redacted = re.sub(
        r"(?i)(access[_-]?token|refresh[_-]?token|id[_-]?token|authorization|cookie)(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[redacted]",
        redacted,
    )
    redacted = re.sub(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        lambda match: mask_identity(match.group(0)),
        redacted,
    )
    return redacted
