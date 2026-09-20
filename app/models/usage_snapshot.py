from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.models.account import AccountRecord


class PageState(str, Enum):
    EMPTY = "empty"
    READY = "ready"
    STALE = "stale"
    ERROR = "error"
    REAUTH_REQUIRED = "reauth_required"
    RATE_LIMITED = "rate_limited"
    SOURCE_CHANGED = "source_changed"


class MetricCard(BaseModel):
    metric_type: str
    label: str
    remaining_pct: Optional[int] = None
    reset_at: Optional[datetime] = None
    window_seconds: Optional[int] = None
    window_minutes: Optional[int] = None
    source_type: str = "unknown"
    source_detail: str = "unknown"


class DetailLink(BaseModel):
    label: str
    url: str
    requires_same_account_login: bool = True


class ResetCredits(BaseModel):
    available_count: int = Field(ge=0)
    # None means details were not returned; individual None values mean unknown expiry.
    expires_at: Optional[list[Optional[datetime]]] = None


class DashboardSummary(BaseModel):
    updated_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    next_sync_at: Optional[datetime] = None
    source_type: str = "scraped"
    source_detail: str = "unknown"
    connector_name: Optional[str] = None
    is_estimated: bool = False


class DashboardPayload(BaseModel):
    account: Optional[AccountRecord] = None
    state: PageState = PageState.EMPTY
    message: Optional[str] = None
    summary: DashboardSummary = Field(default_factory=DashboardSummary)
    metrics: list[MetricCard] = Field(default_factory=list)
    reset_credits: Optional[ResetCredits] = None
    detail_links: list[DetailLink] = Field(default_factory=list)
