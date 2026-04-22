from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CacheEntry:
    expires_at: float
    value: Any


class CacheService:
    def __init__(self, default_ttl_seconds: int = 90) -> None:
        self._default_ttl_seconds = default_ttl_seconds
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if time.time() >= entry.expires_at:
                return None
            return entry.value

    def get_stale(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds or self._default_ttl_seconds
        with self._lock:
            self._entries[key] = CacheEntry(expires_at=time.time() + ttl, value=value)

    def clear(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._entries.clear()
                return
            self._entries.pop(key, None)
