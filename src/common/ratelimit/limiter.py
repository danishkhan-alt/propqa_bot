from __future__ import annotations

import time

from common.cache.factory import get_cache
from common.errors.rate_limited import RateLimited
from common.logger import get_logger
from common.schemas.rate_limit import RateLimit, RateLimitResult
from config import ActiveConfig

logger = get_logger(__name__)


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
    def is_enabled(self) -> bool:
        return ActiveConfig.RATELIMIT_ENABLED

    def enforce(self, identity: str, *rules: RateLimit) -> None:
        for rule in rules:
            result = self._increment_and_evaluate(rule, identity)
            if not result.is_allowed:
                raise RateLimited(result.retry_after)

    def enforce_without_counting(self, identity: str, *rules: RateLimit) -> None:
        for rule in rules:
            result = self.check_without_counting(rule, identity)
            if not result.is_allowed:
                raise RateLimited(result.retry_after)

    def record(self, identity: str, *rules: RateLimit) -> None:
        for rule in rules:
            self._increment_and_evaluate(rule, identity)

    def reset(self, identity: str, *rules: RateLimit) -> None:
        if not self.is_enabled:
            return
        for rule in rules:
            try:
                self._cache.delete(self._counter_key(rule, identity))
            except Exception:
                logger.exception("Could not reset rate limit for %s", rule.scope)

    def check_without_counting(self, rule: RateLimit, identity: str) -> RateLimitResult:
        if not self.is_enabled:
            return RateLimitResult(True, rule.limit, rule.limit, 0)
        try:
            count = self._cache.get(self._counter_key(rule, identity), 0)
        except Exception:
            logger.exception("Rate limit backend unavailable; allowing the request")
            return RateLimitResult(True, rule.limit, rule.limit, 0)
        return self._build_result(rule, int(count or 0), counted=False)

    def _increment_and_evaluate(self, rule: RateLimit, identity: str) -> RateLimitResult:
        if not self.is_enabled:
            return RateLimitResult(True, rule.limit, rule.limit, 0)

        key = self._counter_key(rule, identity)
        try:
            self._cache.add(key, 0, ttl=rule.window_seconds)
            count = self._cache.incr(key)
        except Exception:
            logger.exception(
                "Rate limit backend unavailable; allowing the request",
                extra={"extra_data": {"scope": rule.scope}},
            )
            return RateLimitResult(True, rule.limit, rule.limit, 0)

        result = self._build_result(rule, count, counted=True)
        if not result.is_allowed:
            logger.warning(
                "Rate limit exceeded",
                extra={"extra_data": {"scope": rule.scope, "limit": rule.limit, "count": count}},
            )
        return result

    def _build_result(self, rule: RateLimit, count: int, *, counted: bool) -> RateLimitResult:
        return RateLimitResult(
            is_allowed=count <= rule.limit if counted else count < rule.limit,
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

    def _counter_key(self, rule: RateLimit, identity: str) -> str:
        return f"ratelimit:{rule.scope}:{identity}:{self._window_start(rule)}"


limiter = RateLimiter()
