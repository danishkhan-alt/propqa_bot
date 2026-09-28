"""Who signed in, read from the bearer access token before the caller is resolved."""

from __future__ import annotations

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from auth.errors import InvalidToken
from auth.tokens import decode_access_token
from common.errors import AppError, Unauthorized

BEARER_PREFIX = "bearer "


class AuthMiddleware:
    """Set ``request.state.user_id`` from a valid bearer token.

    A bad or expired token does not fail the request: the caller stays a
    visitor, and the reason is kept for routes that require sign-in.

    Raw ASGI so chat tokens are not buffered until the turn ends.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            _authenticate(Request(scope))
        await self.app(scope, receive, send)


def require_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return user_id
    raise getattr(request.state, "auth_error", None) or Unauthorized()


def _authenticate(request: Request) -> None:
    header = request.headers.get("authorization", "")
    if not header:
        return
    if not header.lower().startswith(BEARER_PREFIX):
        request.state.auth_error = InvalidToken()
        return
    try:
        request.state.user_id = decode_access_token(header[len(BEARER_PREFIX) :].strip())
    except AppError as error:
        request.state.auth_error = error
