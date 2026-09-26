"""A named rate limit, and the verdict for one request against it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimit:
    """How many, how often, and under what name.

    ``scope`` is part of the cache key, so two limits never share a counter
    even when they measure the same caller.
    """

    scope: str
    limit: int
    window_seconds: int

    @property
    def description(self) -> str:
        return f"{self.limit} per {self.window_seconds}s"


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    is_allowed: bool
    limit: int
    remaining: int
    retry_after: int
