"""Who is calling, without holding the response body."""

from __future__ import annotations

import uuid
from http.cookies import SimpleCookie

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from common.enums.user_kind import UserKind
from common.identity import Caller
from common.request_context import subject_id_var, user_kind_var
from common.utils.uuid_validation import is_valid_uuid
from config import ActiveConfig

VISITOR_ID_HEADER = "X-Visitor-ID"


def resolve_caller(request: Request) -> Caller:
    """Registered if auth already set ``user_id``; otherwise a durable visitor."""

    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return Caller(kind=UserKind.REGISTERED, subject_id=str(user_id))

    visitor_id = _read_visitor_id(request) or uuid.uuid4().hex
    return Caller(kind=UserKind.VISITOR, subject_id=visitor_id)


def _read_visitor_id(request: Request) -> str | None:
    header = request.headers.get(VISITOR_ID_HEADER)
    if header and _is_usable_visitor_id(header):
        return header.strip()

    cookie = request.cookies.get(ActiveConfig.VISITOR_COOKIE_NAME)
    if cookie and _is_usable_visitor_id(cookie):
        return cookie.strip()
    return None


def _is_usable_visitor_id(value: str) -> bool:
    cleaned = value.strip()
    return bool(cleaned) and (is_valid_uuid(cleaned) or cleaned.isalnum())


def _build_visitor_cookie_header(caller: Caller) -> str:
    cookie = SimpleCookie()
    cookie[ActiveConfig.VISITOR_COOKIE_NAME] = caller.subject_id
    morsel = cookie[ActiveConfig.VISITOR_COOKIE_NAME]
    morsel["path"] = "/"
    morsel["httponly"] = True
    morsel["samesite"] = "lax"
    morsel["max-age"] = str(ActiveConfig.VISITOR_COOKIE_MAX_AGE)
    return morsel.OutputString()


class CallerMiddleware:
    """Publish who is calling: registered user or visitor.

    Auth middleware (when it exists) should run first and set
    ``request.state.user_id``. This layer then either promotes that to a
    registered caller or mints/reuses a visitor id and sets the cookie.

    Raw ASGI so chat tokens are not buffered until the turn ends.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        caller = resolve_caller(request)
        request.state.caller = caller
        kind_token = user_kind_var.set(caller.kind)
        subject_token = subject_id_var.set(caller.subject_id)

        async def send_with_visitor(message: Message) -> None:
            if message["type"] == "http.response.start" and caller.is_visitor:
                headers = MutableHeaders(raw=message["headers"])
                headers.append("set-cookie", _build_visitor_cookie_header(caller))
                headers[VISITOR_ID_HEADER] = caller.subject_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_visitor)
        finally:
            user_kind_var.reset(kind_token)
            subject_id_var.reset(subject_token)
