from __future__ import annotations

from collections.abc import Callable
from functools import wraps

from common.ratelimit.keys import by_caller
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import RateLimit

RATE_LIMITS_ATTRIBUTE = "rate_limits"


def rate_limit(*rules: RateLimit, key: Callable = by_caller) -> Callable:
    """Override the default ceiling for one endpoint.

    Declaring rules here also tells RateLimitMiddleware to stand back, so
    the two never double-count.
    """

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        async def async_wrapper(request, *args, **kwargs):
            limiter.enforce(key(request), *rules)
            return await view(request, *args, **kwargs)

        @wraps(view)
        def sync_wrapper(request, *args, **kwargs):
            limiter.enforce(key(request), *rules)
            return view(request, *args, **kwargs)

        import asyncio

        wrapper = async_wrapper if asyncio.iscoroutinefunction(view) else sync_wrapper
        existing = getattr(view, RATE_LIMITS_ATTRIBUTE, ())
        setattr(wrapper, RATE_LIMITS_ATTRIBUTE, (*existing, *rules))
        return wrapper

    return decorator
