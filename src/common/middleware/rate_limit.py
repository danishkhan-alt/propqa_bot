"""Default request ceiling, applied before the body starts."""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from common.errors.rate_limited import RateLimited
from common.http.request_response import api_error
from common.identity import Caller
from common.ratelimit.decorators import RATE_LIMITS_ATTRIBUTE
from common.ratelimit.keys import by_ip
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import API_REGISTERED, API_VISITOR

DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json", "/health")


class RateLimitMiddleware:
    """Default ceiling every endpoint gets without anyone remembering to ask.

    Visitors and registered users have separate budgets. A view that declares
    its own limit is skipped here so the two never double-count.

    Raw ASGI so a streaming response is not collected before it is sent.
    """

    def __init__(self, app: ASGIApp, exempt_prefixes: tuple[str, ...] = DEFAULT_EXEMPT_PREFIXES) -> None:
        self.app = app
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        path = request.url.path
        if path.startswith(self.exempt_prefixes) or _declares_own_limit(request):
            await self.app(scope, receive, send)
            return
        try:
            _apply(request)
        except RateLimited as error:
            response = api_error(error, request)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _apply(request: Request) -> None:
    caller = getattr(request.state, "caller", None)
    if isinstance(caller, Caller) and caller.is_registered:
        limiter.enforce(caller.scope, API_REGISTERED)
        return
    if isinstance(caller, Caller) and caller.is_visitor:
        limiter.enforce(caller.scope, API_VISITOR)
        return
    limiter.enforce(by_ip(request), API_VISITOR)


def _declares_own_limit(request: Request) -> bool:
    endpoint = _endpoint(request)
    return bool(endpoint is not None and getattr(endpoint, RATE_LIMITS_ATTRIBUTE, None))


def _endpoint(request: Request):
    """The view for this path. Routing has not run yet, so match it here."""
    found = request.scope.get("endpoint")
    if found is not None:
        return found
    method = request.method
    for path, route in _walk_routes(getattr(request.app, "routes", ())):
        if path != request.url.path:
            continue
        methods = getattr(route, "methods", None)
        if methods and method not in methods:
            continue
        return getattr(route, "endpoint", None)
    return None


def _walk_routes(routes, prefix: str = ""):
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            extra = getattr(getattr(route, "include_context", None), "prefix", "") or ""
            yield from _walk_routes(included.routes, prefix + extra)
            continue
        path = getattr(route, "path", None)
        if path:
            yield prefix + path, route
