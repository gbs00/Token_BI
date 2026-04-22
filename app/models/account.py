from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AccountStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    INVALID = "invalid"


class AccountRecord(BaseModel):
    account_id: str
    account_alias: str
    masked_email: str
    status: AccountStatus
    session_storage_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_validated_at: Optional[datetime] = None


class CreateAccountRequest(BaseModel):
    account_alias: Optional[str] = None
    masked_email: str
