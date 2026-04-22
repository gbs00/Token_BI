from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BrowserSessionState(str, Enum):
    STOPPED = "stopped"
    AWAITING_LOGIN = "awaiting_login"
    READY = "ready"
    ERROR = "error"


class BrowserSessionSnapshot(BaseModel):
    account_id: str
    state: BrowserSessionState
    context_dir: str
    debug_port: Optional[int] = None
    browser_app_name: Optional[str] = None
    current_url: Optional[str] = None
    last_error: Optional[str] = None
    launched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: Optional[datetime] = None
