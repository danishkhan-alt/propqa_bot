"""Request id on every call, without holding the response body."""

from __future__ import annotations

import uuid

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from common.context import get_request_id, request_id_var

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    """Attach a unique request ID to every request for tracing.

    Honours an inbound ``X-Request-ID`` when a client or upstream proxy
    already has one; otherwise mints a new id. Echoes it on the response
    so clients can cite it in support tickets.

    This is raw ASGI, not ``BaseHTTPMiddleware``, so a streaming body is
    forwarded one chunk at a time.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(raw=message["headers"])
                headers[REQUEST_ID_HEADER] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


__all__ = ["REQUEST_ID_HEADER", "RequestIdMiddleware", "get_request_id"]
