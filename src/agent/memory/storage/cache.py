"""Hot keys: working memory, profile cache, recall cache, and the extraction stream."""

from __future__ import annotations

import json
import time
from typing import Any

WM_TTL_SECONDS = 60 * 60 * 2
RECALL_TTL_SECONDS = 60 * 5
PROFILE_TTL_SECONDS = 60 * 15
STREAM = "memq"
GROUP = "memory-worker"
CONSUMER = "worker-1"


class WorkingMemoryCache:
    """Process stand-in for the Redis keys in the memory spec."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[Any, float | None]] = {}
        self._stream: list[tuple[str, dict]] = []
        self._seq = 0

    def get(self, key: str) -> Any:
        item = self._values.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= time.monotonic():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires = None if ttl is None else time.monotonic() + ttl
        self._values[key] = (value, expires)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def delete_prefix(self, prefix: str) -> None:
        for key in list(self._values):
            if key.startswith(prefix):
                self._values.pop(key, None)

    def push(self, job: dict) -> str:
        self._seq += 1
        entry_id = str(self._seq)
        self._stream.append((entry_id, job))
        return entry_id

    def read(self, *, count: int = 10, block_ms: int = 0) -> list[tuple[str, dict]]:
        del block_ms
        batch = self._stream[:count]
        self._stream = self._stream[count:]
        return batch

    def ack(self, entry_id: str) -> None:
        del entry_id

    def close(self) -> None:
        return None


class RedisMemoryCache:
    """Exact key names from the spec: `wm:{thread}`, `profile:{user}`, `recall:…`, `memq`."""

    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url, decode_responses=True)

    def get(self, key: str) -> Any:
        raw = self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        payload = json.dumps(value, default=str)
        if ttl is None:
            self._redis.set(key, payload)
        else:
            self._redis.set(key, payload, ex=ttl)

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def delete_prefix(self, prefix: str) -> None:
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor=cursor, match=f"{prefix}*", count=200)
            if keys:
                self._redis.delete(*keys)
            if cursor == 0:
                return

    def push(self, job: dict) -> str:
        entry_id = self._redis.xadd(
            STREAM,
            {"job": json.dumps(job, default=str)},
            maxlen=10000,
            approximate=True,
        )
        return str(entry_id)

    def read(self, *, count: int = 10, block_ms: int = 2000) -> list[tuple[str, dict]]:
        self._ensure_group()
        rows = self._redis.xreadgroup(
            GROUP,
            CONSUMER,
            {STREAM: ">"},
            count=count,
            block=block_ms,
        )
        jobs: list[tuple[str, dict]] = []
        for _stream, entries in rows or []:
            for entry_id, fields in entries:
                payload = fields.get("job") if isinstance(fields, dict) else None
                if not payload:
                    continue
                jobs.append((str(entry_id), json.loads(payload)))
        return jobs

    def ack(self, entry_id: str) -> None:
        self._redis.xack(STREAM, GROUP, entry_id)

    def close(self) -> None:
        self._redis.close()

    def _ensure_group(self) -> None:
        try:
            self._redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
