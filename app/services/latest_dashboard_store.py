from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from app.models.account import AccountRecord
from app.models.usage_snapshot import (
    DashboardPayload,
    DashboardSummary,
    DetailLink,
    MetricCard,
    PageState,
)
from app.services.usage_connectors import mask_identity


class LatestDashboardStore:
    """只持久化最后一次成功额度，不保存历史或连接凭据。"""

    VERSION = 1

    def __init__(self, snapshot_path: Path) -> None:
        self._snapshot_path = snapshot_path
        self._lock = threading.RLock()

    @property
    def snapshot_path(self) -> Path:
        return self._snapshot_path

    def load(self, account: Optional[AccountRecord]) -> Optional[DashboardPayload]:
        if account is None:
            return None
        with self._lock:
            if not self._snapshot_path.exists():
                return None
            try:
                raw = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    return None
                if raw.get("version") != self.VERSION:
                    return None
                if raw.get("account_id") != account.account_id:
                    self._clear_unlocked()
                    return None
                stored_identity = str(raw.get("account_masked_email") or "").strip()
                if stored_identity and stored_identity != account.masked_email:
                    self._clear_unlocked()
                    return None
                return DashboardPayload(
                    account=account,
                    state=PageState.READY,
                    summary=DashboardSummary.model_validate(raw.get("summary") or {}),
                    metrics=[MetricCard.model_validate(item) for item in raw.get("metrics") or []],
                    detail_links=[
                        DetailLink.model_validate(item) for item in raw.get("detail_links") or []
                    ],
                )
            except (json.JSONDecodeError, OSError, TypeError, ValidationError):
                return None

    def save(self, payload: DashboardPayload) -> None:
        if payload.account is None or payload.state != PageState.READY or not payload.metrics:
            raise ValueError("Only successful dashboard payloads can be persisted.")

        stored = {
            "version": self.VERSION,
            "account_id": payload.account.account_id,
            "account_masked_email": mask_identity(payload.account.masked_email),
            "summary": payload.summary.model_dump(mode="json"),
            "metrics": [metric.model_dump(mode="json") for metric in payload.metrics],
            "detail_links": [link.model_dump(mode="json") for link in payload.detail_links],
        }
        encoded = json.dumps(stored, ensure_ascii=False, indent=2) + "\n"

        with self._lock:
            self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".tmp")
            descriptor = os.open(
                temporary_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, self._snapshot_path)
                os.chmod(self._snapshot_path, 0o600)
            finally:
                temporary_path.unlink(missing_ok=True)

    def clear(self, account_id: Optional[str] = None) -> None:
        with self._lock:
            if account_id is not None and self._snapshot_path.exists():
                try:
                    raw = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    raw = {}
                if not isinstance(raw, dict):
                    raw = {}
                if raw.get("account_id") not in {None, account_id}:
                    return
            self._clear_unlocked()

    def _clear_unlocked(self) -> None:
        self._snapshot_path.unlink(missing_ok=True)
        self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".tmp").unlink(missing_ok=True)
