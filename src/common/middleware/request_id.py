from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from common.context import get_request_id, request_id_var

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every request for tracing.

    Honours an inbound ``X-Request-ID`` when a client or upstream proxy
    already has one; otherwise mints a new id. Echoes it on the response
    so clients can cite it in support tickets.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            request_id_var.reset(token)


__all__ = ["REQUEST_ID_HEADER", "RequestIdMiddleware", "get_request_id"]
