from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Protocol

from app.models.account import AccountRecord
from app.services.browser_worker_service import BrowserWorkerService
from app.services.scraper_service import (
    AnalyticsPageChangedError,
    ScraperUnavailableError,
    SessionExpiredError,
)


class ConnectorNotApplicableError(ScraperUnavailableError):
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

        normalized = self._normalize_payload(payload)
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail="local_snapshot_json",
            payload=normalized,
        )

    def _normalize_payload(self, payload: dict) -> dict:
        required_keys = {
            "session_remaining_pct",
            "session_reset_at",
            "weekly_remaining_pct",
            "weekly_reset_at",
        }
        if not required_keys.issubset(payload.keys()):
            missing = ", ".join(sorted(required_keys - set(payload.keys())))
            raise AnalyticsPageChangedError(
                f"Local connector snapshot is missing required fields: {missing}"
            )

        normalized = {
            "session_remaining_pct": int(payload["session_remaining_pct"]),
            "session_reset_at": self._coerce_datetime(payload["session_reset_at"]),
            "weekly_remaining_pct": int(payload["weekly_remaining_pct"]),
            "weekly_reset_at": self._coerce_datetime(payload["weekly_reset_at"]),
            "updated_at": self._coerce_datetime(payload.get("updated_at"))
            or datetime.now().astimezone(),
            "is_estimated": bool(payload.get("is_estimated", False)),
        }
        if payload.get("account_masked_email"):
            normalized["account_masked_email"] = str(payload["account_masked_email"])
        return normalized

    def _coerce_datetime(self, value) -> Optional[datetime]:
        if value in {None, ""}:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        raise AnalyticsPageChangedError(f"Unsupported datetime value: {value}")


class WebSessionConnector:
    name = "browser_worker"
    source_type = "scraped"

    def __init__(self, browser_worker_service: BrowserWorkerService) -> None:
        self._browser_worker_service = browser_worker_service

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        payload = self._browser_worker_service.fetch_usage(account)
        return UsageConnectorResult(
            connector_name=self.name,
            source_type=self.source_type,
            source_detail=str(payload.get("source_detail", "live_browser_unknown")),
            payload=payload,
        )


class UsageConnectorManager:
    def __init__(self, connectors: Iterable[UsageConnector]) -> None:
        self._connectors = list(connectors)

    def fetch_usage(self, account: AccountRecord) -> UsageConnectorResult:
        errors: list[str] = []
        for connector in self._connectors:
            try:
                return connector.fetch_usage(account)
            except ConnectorNotApplicableError:
                continue
            except SessionExpiredError:
                raise
            except ScraperUnavailableError as exc:
                errors.append(f"{connector.name}: {exc}")
                continue

        if errors:
            raise ScraperUnavailableError(" | ".join(errors))
        raise ScraperUnavailableError("No usage connector available for this account.")
