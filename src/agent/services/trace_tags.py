"""Fields written onto the Langfuse span for one chat turn."""

from __future__ import annotations

from agent.schemas.routes import as_domain_route, as_query_route
from agent.services.prompt_version import prompt_version
from common.logger import get_logger

logger = get_logger("agent.runner")


def turn_trace_metadata(values: dict | None, *, fallback_fired: bool) -> dict:
    route, domain_ids = _route_and_domains(values)
    return {
        "prompt_version": prompt_version(),
        "route": route,
        "domain_ids": domain_ids,
        "fallback_fired": bool(fallback_fired),
    }


def tag_turn_span(span, values: dict | None, *, fallback_fired: bool) -> None:
    """Attach the four turn fields to the span that owns this trace."""
    if span is None or not hasattr(span, "update"):
        return
    try:
        span.update(metadata=turn_trace_metadata(values, fallback_fired=fallback_fired))
    except Exception:
        logger.warning("langfuse trace tags failed", exc_info=True)


def _route_and_domains(values: dict | None) -> tuple[str, list[str]]:
    if not isinstance(values, dict):
        return "", []
    try:
        query = as_query_route(values.get("query_route"))
    except Exception:
        query = None
    try:
        domain = as_domain_route(values.get("domain_route"))
    except Exception:
        domain = None
    route = query.route.value if query is not None else ""
    domain_ids = [str(item) for item in (domain.domain_ids if domain is not None else []) if str(item).strip()]
    return route, domain_ids
