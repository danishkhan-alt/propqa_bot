from __future__ import annotations

from contextvars import ContextVar

from common.enums.user_kind import UserKind

#: Ambient facts about the work in flight. One definition, imported by
#: loggers, middleware, and error responses -- two modules each declaring
#: ``ContextVar("request_id")`` would be two different variables.

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_kind_var: ContextVar[UserKind | None] = ContextVar("user_kind", default=None)
subject_id_var: ContextVar[str | None] = ContextVar("subject_id", default=None)


def get_request_id(request=None) -> str | None:
    """Prefer the id the middleware set on the request; fall back to context."""

    if request is not None:
        request_id = getattr(getattr(request, "state", None), "request_id", None)
        if request_id:
            return request_id
        request_id = getattr(request, "request_id", None)
        if request_id:
            return request_id
    return request_id_var.get()
