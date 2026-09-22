from __future__ import annotations

import time
from dataclasses import dataclass

from common.cache.factory import get_cache
from common.errors.rate_limited import RateLimited
from common.logger import get_logger
from common.ratelimit.rules import RateLimit
from config import ActiveConfig

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter:
    """Fixed-window counting, backed by the shared cache.

    Correct only because the counter is shared. Per-process counting with
    four workers permits four times what the limit says, which is why
    deployed environments require Redis.

    **Fails open.** If the cache is unreachable the request proceeds and the
    failure is logged. Locking every caller out because Redis blinked is a
    worse outage than a gap in throttling.
    """

    def __init__(self, backend=None) -> None:
        self._explicit_backend = backend

    @property
    def _cache(self):
        return self._explicit_backend if self._explicit_backend is not None else get_cache()

    @property
    def enabled(self) -> bool:
        return ActiveConfig.RATELIMIT_ENABLED

    def enforce(self, identity: str, *rules: RateLimit) -> None:
        for rule in rules:
            result = self._count(rule, identity)
            if not result.allowed:
                raise RateLimited(result.retry_after)

    def guard(self, identity: str, *rules: RateLimit) -> None:
        for rule in rules:
            result = self.inspect(rule, identity)
            if not result.allowed:
                raise RateLimited(result.retry_after)

    def record(self, identity: str, *rules: RateLimit) -> None:
        for rule in rules:
            self._count(rule, identity)

    def reset(self, identity: str, *rules: RateLimit) -> None:
        if not self.enabled:
            return
        for rule in rules:
            try:
                self._cache.delete(self._key(rule, identity))
            except Exception:
                logger.exception("Could not reset rate limit for %s", rule.scope)

    def inspect(self, rule: RateLimit, identity: str) -> RateLimitResult:
        if not self.enabled:
            return RateLimitResult(True, rule.limit, rule.limit, 0)
        try:
            count = self._cache.get(self._key(rule, identity), 0)
        except Exception:
            logger.exception("Rate limit backend unavailable; allowing the request")
            return RateLimitResult(True, rule.limit, rule.limit, 0)
        return self._result(rule, int(count or 0), counted=False)

    def _count(self, rule: RateLimit, identity: str) -> RateLimitResult:
        if not self.enabled:
            return RateLimitResult(True, rule.limit, rule.limit, 0)

        key = self._key(rule, identity)
        try:
            self._cache.add(key, 0, ttl=rule.window_seconds)
            count = self._cache.incr(key)
        except Exception:
            logger.exception(
                "Rate limit backend unavailable; allowing the request",
                extra={"extra_data": {"scope": rule.scope}},
            )
            return RateLimitResult(True, rule.limit, rule.limit, 0)

        result = self._result(rule, count, counted=True)
        if not result.allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"extra_data": {"scope": rule.scope, "limit": rule.limit, "count": count}},
            )
        return result

    def _result(self, rule: RateLimit, count: int, *, counted: bool) -> RateLimitResult:
        return RateLimitResult(
            allowed=count <= rule.limit if counted else count < rule.limit,
            limit=rule.limit,
            remaining=max(0, rule.limit - count),
            retry_after=self._seconds_left(rule),
        )

    @staticmethod
    def _window_start(rule: RateLimit) -> int:
        now = int(time.time())
        return now - (now % rule.window_seconds)

    def _seconds_left(self, rule: RateLimit) -> int:
        return self._window_start(rule) + rule.window_seconds - int(time.time())

    def _key(self, rule: RateLimit, identity: str) -> str:
        return f"ratelimit:{rule.scope}:{identity}:{self._window_start(rule)}"


limiter = RateLimiter()
