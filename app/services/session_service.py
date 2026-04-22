from __future__ import annotations

from pathlib import Path

from app.config import Settings


class SessionService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def context_dir(self, account_id: str) -> Path:
        return self._settings.runtime_contexts_dir / account_id

    def ensure_context_dir(self, account_id: str) -> Path:
        context_dir = self.context_dir(account_id)
        context_dir.mkdir(parents=True, exist_ok=True)
        return context_dir

    def context_has_material(self, account_id: str) -> bool:
        context_dir = self.context_dir(account_id)
        if not context_dir.exists() or not context_dir.is_dir():
            return False
        return any(context_dir.iterdir())

