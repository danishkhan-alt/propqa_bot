from __future__ import annotations

from collections.abc import Callable

from common.schemas.rate_limit import RateLimit

RATE_LIMITS_ATTRIBUTE = "rate_limits"


def declare_rate_limits(view: Callable, *rules: RateLimit) -> None:
    """Mark a view that enforces its own limits.

    The view still calls the limiter itself; this only tells
    RateLimitMiddleware to stand back, so the two never double-count.
    """
    existing = getattr(view, RATE_LIMITS_ATTRIBUTE, ())
    setattr(view, RATE_LIMITS_ATTRIBUTE, (*existing, *rules))


def declared_rate_limits(view: Callable | None) -> tuple[RateLimit, ...]:
    return getattr(view, RATE_LIMITS_ATTRIBUTE, ()) if view is not None else ()
