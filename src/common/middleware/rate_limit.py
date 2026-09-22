from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from common.errors.rate_limited import RateLimited
from common.http.request_response import api_error
from common.identity import Caller
from common.logger import get_logger
from common.ratelimit.decorators import RATE_LIMITS_ATTRIBUTE
from common.ratelimit.keys import by_ip
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import API_REGISTERED, API_VISITOR

logger = get_logger(__name__)

DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json", "/health")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Default ceiling every endpoint gets without anyone remembering to ask.

    Visitors and registered users have separate budgets. A view that declares
    ``@rate_limit`` is skipped here so the two never double-count.
    """

    def __init__(self, app, exempt_prefixes: tuple[str, ...] = DEFAULT_EXEMPT_PREFIXES) -> None:
        super().__init__(app)
        self.exempt_prefixes = exempt_prefixes

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith(self.exempt_prefixes):
            return await call_next(request)

        endpoint = request.scope.get("endpoint")
        if endpoint is not None and getattr(endpoint, RATE_LIMITS_ATTRIBUTE, None):
            return await call_next(request)

        try:
            self._apply(request)
        except RateLimited as error:
            return api_error(error, request)
        return await call_next(request)

    def _apply(self, request: Request) -> None:
        caller = getattr(request.state, "caller", None)
        if isinstance(caller, Caller) and caller.is_registered:
            limiter.enforce(caller.scope, API_REGISTERED)
            return
        if isinstance(caller, Caller) and caller.is_visitor:
            limiter.enforce(caller.scope, API_VISITOR)
            return
        limiter.enforce(by_ip(request), API_VISITOR)
