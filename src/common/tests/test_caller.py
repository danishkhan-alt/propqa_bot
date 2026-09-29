from __future__ import annotations

from starlette.requests import Request

from common.enums.user_kind import UserKind
from common.middleware.caller import resolve_caller
from config import ActiveConfig


def _request(headers: list[tuple[bytes, bytes]] | None = None, cookies: str | None = None) -> Request:
    raw_headers = list(headers or [])
    if cookies:
        raw_headers.append((b"cookie", cookies.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "asgi": {"spec_version": "2.3", "version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/chat",
            "raw_path": b"/api/chat",
            "query_string": b"",
            "headers": raw_headers,
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
    )


def test_missing_identity_becomes_a_visitor():
    caller = resolve_caller(_request())
    assert caller.is_visitor
    assert caller.subject_id


def test_visitor_header_is_reused():
    caller = resolve_caller(_request(headers=[(b"x-visitor-id", b"abc123visitor")]))
    assert caller.kind is UserKind.VISITOR
    assert caller.subject_id == "abc123visitor"


def test_visitor_cookie_is_reused():
    caller = resolve_caller(
        _request(cookies=f"{ActiveConfig.VISITOR_COOKIE_NAME}=cookievisitor1")
    )
    assert caller.is_visitor
    assert caller.subject_id == "cookievisitor1"


def test_registered_user_wins_over_visitor_cookie():
    request = _request(cookies=f"{ActiveConfig.VISITOR_COOKIE_NAME}=cookievisitor1")
    request.state.user_id = "user-42"
    caller = resolve_caller(request)
    assert caller.is_registered
    assert caller.subject_id == "user-42"


def test_oversized_visitor_header_is_replaced():
    caller = resolve_caller(_request(headers=[(b"x-visitor-id", b"a" * 65)]))
    assert caller.is_visitor
    assert caller.subject_id != "a" * 65
