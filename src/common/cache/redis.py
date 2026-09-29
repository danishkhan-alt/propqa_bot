from __future__ import annotations

import json
from typing import Any

import redis

from common.cache.protocol import MISSING

# INCR only a key that exists, so a counter that expired between ``add`` and
# ``incr`` is reported as missing instead of being recreated without a TTL.
_INCR_EXISTING = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return redis.call('INCR', KEYS[1])
end
return false
"""


def _encode(value: Any) -> str:
    # Integers are stored bare so Redis can increment them in place.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return json.dumps({"v": value}, default=str)


def _decode(raw: str) -> Any:
    payload = json.loads(raw)
    if isinstance(payload, dict) and "v" in payload:
        return payload["v"]
    return payload


class RedisCache:
    """Shared cache. Required in deployed environments."""

    def __init__(self, url: str, *, prefix: str = "") -> None:
        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix.rstrip(":")
        self._incr_existing = self._client.register_script(_INCR_EXISTING)

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}" if self._prefix else key

    def get(self, key: str, default: Any = MISSING) -> Any:
        raw = self._client.get(self._key(key))
        if raw is None:
            return default
        return _decode(raw)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._client.set(self._key(key), _encode(value), ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def add(self, key: str, value: Any, ttl: int | None = None) -> bool:
        return bool(self._client.set(self._key(key), _encode(value), nx=True, ex=ttl))

    def incr(self, key: str) -> int:
        """Atomic, and keeps the key's TTL."""
        result = self._incr_existing(keys=[self._key(key)])
        if result is None:
            raise KeyError(key)
        return int(result)
