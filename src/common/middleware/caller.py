from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from common.context import subject_id_var, user_kind_var
from common.enums.user_kind import UserKind
from common.identity import Caller
from common.utils.helpers import is_valid_uuid
from config import ActiveConfig

VISITOR_HEADER = "X-Visitor-ID"


def resolve_caller(request: Request) -> Caller:
    """Registered if auth already set ``user_id``; otherwise a durable visitor."""

    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return Caller(kind=UserKind.REGISTERED, subject_id=str(user_id))

    visitor_id = _read_visitor_id(request) or uuid.uuid4().hex
    return Caller(kind=UserKind.VISITOR, subject_id=visitor_id)


def _read_visitor_id(request: Request) -> str | None:
    header = request.headers.get(VISITOR_HEADER)
    if header and _usable_id(header):
        return header.strip()

    cookie = request.cookies.get(ActiveConfig.VISITOR_COOKIE_NAME)
    if cookie and _usable_id(cookie):
        return cookie.strip()
    return None


def _usable_id(value: str) -> bool:
    cleaned = value.strip()
    return bool(cleaned) and (is_valid_uuid(cleaned) or cleaned.isalnum())


class CallerMiddleware(BaseHTTPMiddleware):
    """Publish who is calling: registered user or visitor.

    Auth middleware (when it exists) should run first and set
    ``request.state.user_id``. This layer then either promotes that to a
    registered caller or mints/reuses a visitor id and sets the cookie.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        caller = resolve_caller(request)
        request.state.caller = caller

        kind_token = user_kind_var.set(caller.kind)
        subject_token = subject_id_var.set(caller.subject_id)
        try:
            response = await call_next(request)
        finally:
            user_kind_var.reset(kind_token)
            subject_id_var.reset(subject_token)

        if caller.is_visitor:
            response.set_cookie(
                ActiveConfig.VISITOR_COOKIE_NAME,
                caller.subject_id,
                max_age=ActiveConfig.VISITOR_COOKIE_MAX_AGE,
                httponly=True,
                samesite="lax",
            )
            response.headers[VISITOR_HEADER] = caller.subject_id
        return response
