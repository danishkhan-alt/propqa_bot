from __future__ import annotations

import json
from typing import Any

from common.cache.protocol import MISSING


def _encode(value: Any) -> str:
    return json.dumps({"v": value}, default=str)


def _decode(raw: str | bytes | None) -> Any:
    if raw is None:
        return MISSING
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return int(raw)
    if isinstance(payload, dict) and "v" in payload:
        return payload["v"]
    return payload


class RedisCache:
    """Shared cache. Required in deployed environments."""

    def __init__(self, url: str, *, prefix: str = "") -> None:
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix.rstrip(":")

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}" if self._prefix else key

    def get(self, key: str, default: Any = MISSING) -> Any:
        raw = self._client.get(self._key(key))
        if raw is None:
            return default
        return _decode(raw)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        encoded = _encode(value)
        namespaced = self._key(key)
        if ttl is None:
            self._client.set(namespaced, encoded)
        else:
            self._client.set(namespaced, encoded, ex=ttl)

    def delete(self, key: str) -> None:
        self._client.delete(self._key(key))

    def add(self, key: str, value: Any, ttl: int | None = None) -> bool:
        namespaced = self._key(key)
        if ttl is None:
            return bool(self._client.set(namespaced, _encode(value), nx=True))
        return bool(self._client.set(namespaced, _encode(value), nx=True, ex=ttl))

    def incr(self, key: str) -> int:
        namespaced = self._key(key)
        raw = self._client.get(namespaced)
        if raw is None:
            raise KeyError(key)
        next_value = int(_decode(raw)) + 1
        ttl = self._client.ttl(namespaced)
        if ttl and ttl > 0:
            self._client.set(namespaced, _encode(next_value), ex=ttl)
        else:
            self._client.set(namespaced, _encode(next_value))
        return next_value

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        if not keys:
            return {}
        raw_values = self._client.mget([self._key(key) for key in keys])
        found: dict[str, Any] = {}
        for key, raw in zip(keys, raw_values, strict=True):
            if raw is None:
                continue
            found[key] = _decode(raw)
        return found

    def clear(self) -> None:
        self._client.flushdb()
