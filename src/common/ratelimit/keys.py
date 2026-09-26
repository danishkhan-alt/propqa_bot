from __future__ import annotations

from starlette.requests import Request

from common.identity import Caller
from config import ActiveConfig


def client_ip(request: Request) -> str:
    """The caller's address, trusting only as many proxies as we run.

    ``X-Forwarded-For`` is client-supplied. Count in from the right by
    ``TRUSTED_PROXY_COUNT``: each proxy we control appends the address it
    saw, so the Nth from the end is the last hop we can vouch for.
    """
    trusted = ActiveConfig.TRUSTED_PROXY_COUNT
    if trusted > 0:
        forwarded = request.headers.get("X-Forwarded-For", "")
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(chain) >= trusted:
            return chain[-trusted]

    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def ip_rate_limit_key(request: Request) -> str:
    return f"ip:{client_ip(request)}"


def caller_rate_limit_key(request: Request) -> str:
    caller = getattr(request.state, "caller", None)
    if isinstance(caller, Caller):
        return caller.identity_key
    return ip_rate_limit_key(request)
