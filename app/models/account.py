from __future__ import annotations

import hashlib
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
    identity_key: Optional[str] = None


def same_account_identity(left: Optional[AccountRecord], right: Optional[AccountRecord]) -> bool:
    if left is None or right is None:
        return left is right
    return (
        left.account_id == right.account_id
        and left.masked_email == right.masked_email
        and left.identity_key == right.identity_key
    )


def identity_key(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


class CreateAccountRequest(BaseModel):
    account_alias: Optional[str] = None
    masked_email: Optional[str] = None
