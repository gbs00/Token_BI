from __future__ import annotations

import base64
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.models.account import AccountRecord
from app.services.browser_worker_service import BrowserWorkerService, LiveSessionRequiredError
from app.services.scraper_service import (
    AnalyticsPageChangedError,
    ScraperUnavailableError,
    SessionExpiredError,
)


class ConnectorNotApplicableError(ScraperUnavailableError):
    pass


class ConnectorRateLimitedError(ScraperUnavailableError):
    pass


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
            self._read_access_token()
        except ScraperUnavailableError:
            return False
        return True

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        access_token = self._read_access_token()
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
        account_identity = self._extract_account_identity(access_token)
        if account_identity:
            normalized["account_masked_email"] = account_identity
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail="oauth_usage_api",
            payload=normalized,
        )

    def _read_access_token(self) -> str:
        for path in self._auth_paths:
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ScraperUnavailableError("Codex auth file is unreadable.") from exc

            tokens = payload.get("tokens")
            if not isinstance(tokens, dict):
                continue
            access_token = tokens.get("access_token") or tokens.get("accessToken")
            if isinstance(access_token, str) and access_token.strip():
                return access_token.strip()

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
        payload = self._decode_jwt_payload(token)
        if payload is None:
            return None
        profile = payload.get("https://api.openai.com/profile")
        if isinstance(profile, dict):
            email = profile.get("email")
            if isinstance(email, str) and email.strip():
                return mask_identity(email)
        email = payload.get("email")
        if isinstance(email, str) and email.strip():
            return mask_identity(email)
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
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise SessionExpiredError("Codex login is not authorized for usage data.") from exc
            if exc.code == 429:
                raise ConnectorRateLimitedError("Codex usage endpoint is rate limited.") from exc
            if exc.code >= 500:
                raise ScraperUnavailableError("Codex usage endpoint is temporarily unavailable.") from exc
            raise ScraperUnavailableError(f"Codex usage endpoint returned HTTP {exc.code}.") from exc
        except (URLError, OSError) as exc:
            raise ScraperUnavailableError("Unable to reach Codex usage endpoint.") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
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

        account_payload = self._rpc("account/read", {"refreshToken": False})
        account_identity = self._extract_account_identity(account_payload)
        if account_payload.get("requiresOpenaiAuth") and account_payload.get("account") is None:
            raise SessionExpiredError("Codex CLI is not signed in. Please complete Codex login.")

        rate_limit_payload = self._rpc("account/rateLimits/read", None)
        normalized = normalize_usage_payload(
            rate_limit_payload,
            source_type=self.source_type,
            source_detail="cli_rate_limits",
        )
        if account_identity:
            normalized["account_masked_email"] = account_identity
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail="cli_rate_limits",
            payload=normalized,
        )

    def _rpc(self, method: str, params: Any) -> dict:
        if self._rpc_client is not None:
            return self._rpc_client(method, params)
        return self._default_rpc(method, params)

    def _default_rpc(self, method: str, params: Any) -> dict:
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
                        "clientInfo": {"name": "token-bi", "version": "1.0.0"},
                        "capabilities": {"experimentalApi": True},
                    },
                },
            )
            self._read_jsonrpc_response(process, request_id=1)
            self._write_jsonrpc(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": method,
                    "params": params,
                },
            )
            response = self._read_jsonrpc_response(process, request_id=2)
        finally:
            self._stop_rpc_process(process)

        if "error" in response:
            raise ScraperUnavailableError("Codex app-server returned an RPC error.")
        result = response.get("result")
        if not isinstance(result, dict):
            raise AnalyticsPageChangedError("Codex app-server returned an unsupported payload.")
        return result

    def _write_jsonrpc(self, process: subprocess.Popen, request: dict) -> None:
        if process.stdin is None:
            raise ScraperUnavailableError("Codex app-server RPC is not writable.")
        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
        except OSError as exc:
            raise ScraperUnavailableError("Codex app-server RPC is not writable.") from exc

    def _read_jsonrpc_response(self, process: subprocess.Popen, request_id: int) -> dict:
        if process.stdout is None:
            raise ScraperUnavailableError("Codex app-server RPC is not readable.")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        if process.stderr is not None:
            selector.register(process.stderr, selectors.EVENT_READ)
        deadline = time.time() + self._timeout_seconds
        stderr_tail = ""
        try:
            while time.time() < deadline:
                events = selector.select(timeout=0.1)
                for key, _ in events:
                    line = key.fileobj.readline()
                    if not line:
                        continue
                    if key.fileobj is process.stderr:
                        stderr_tail = (stderr_tail + line)[-300:]
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("id") == request_id:
                        return payload
                if process.poll() is not None and not events:
                    break
        finally:
            selector.close()
        detail = redact_sensitive_text(stderr_tail.strip())
        if detail:
            raise ScraperUnavailableError(f"Codex app-server RPC timed out: {detail}")
        raise ScraperUnavailableError("Codex app-server RPC timed out.")

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
        errors: list[tuple[str, ScraperUnavailableError]] = []
        for connector in self._connectors:
            try:
                result = connector.fetch_usage(account)
                self.last_connector_errors = self._serialize_errors(errors)
                return result
            except ConnectorNotApplicableError as exc:
                errors.append((connector.name, exc))
                continue
            except LiveSessionRequiredError as exc:
                errors.append((connector.name, exc))
                continue
            except SessionExpiredError as exc:
                errors.append((connector.name, exc))
                continue
            except ConnectorRateLimitedError as exc:
                errors.append((connector.name, exc))
                continue
            except AnalyticsPageChangedError as exc:
                errors.append((connector.name, exc))
                continue
            except ScraperUnavailableError as exc:
                errors.append((connector.name, exc))
                continue

        self.last_connector_errors = self._serialize_errors(errors)
        if not errors:
            raise ScraperUnavailableError("No usage connector available for this account.")

        for error_type in (
            SessionExpiredError,
            ConnectorRateLimitedError,
            AnalyticsPageChangedError,
            LiveSessionRequiredError,
        ):
            matching = [exc for _, exc in errors if isinstance(exc, error_type)]
            if matching:
                raise matching[0]

        details = " | ".join(f"{name}: {exc}" for name, exc in errors)
        raise ScraperUnavailableError(details)

    def _serialize_errors(self, errors: list[tuple[str, ScraperUnavailableError]]) -> list[dict[str, str]]:
        return [
            {
                "connector_name": name,
                "error_type": exc.__class__.__name__,
                "message": redact_sensitive_text(str(exc)),
            }
            for name, exc in errors
        ]


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
        return _clamp_pct(100 - int(float(used)))
    return None


def _window_seconds(raw_window: dict) -> Optional[int]:
    value = _first_present(
        raw_window,
        ("window_seconds", "windowSeconds", "limit_window_seconds", "limitWindowSeconds"),
    )
    if value is None:
        return None
    return int(value)


def _window_minutes(raw_window: dict, window_seconds: Optional[int]) -> Optional[int]:
    value = _first_present(
        raw_window,
        ("window_minutes", "windowMinutes", "windowDurationMins"),
    )
    if value is not None:
        return int(value)
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
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise AnalyticsPageChangedError(f"Unsupported datetime payload: {type(value).__name__}")


def _clamp_pct(value: Any) -> int:
    pct = int(float(value))
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
