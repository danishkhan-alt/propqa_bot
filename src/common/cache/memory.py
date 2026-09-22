from __future__ import annotations

import time
from typing import Any

from common.cache.protocol import MISSING


class MemoryCache:
    """Process-local backend for tests and Redis-less local runs."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    def get(self, key: str, default: Any = MISSING) -> Any:
        entry = self._store.get(key)
        if entry is None:
            return default
        value, expires_at = entry
        if expires_at is not None and expires_at <= time.time():
            self._store.pop(key, None)
            return default
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires_at = None if ttl is None else time.time() + ttl
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def add(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if self.get(key, MISSING) is not MISSING:
            return False
        self.set(key, value, ttl)
        return True

    def incr(self, key: str) -> int:
        current = self.get(key, MISSING)
        if current is MISSING:
            raise KeyError(key)
        next_value = int(current) + 1
        expires_at = self._store[key][1]
        ttl = None if expires_at is None else max(1, int(expires_at - time.time()))
        self.set(key, next_value, ttl)
        return next_value

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for key in keys:
            value = self.get(key, MISSING)
            if value is not MISSING:
                found[key] = value
        return found

    def clear(self) -> None:
        self._store.clear()
