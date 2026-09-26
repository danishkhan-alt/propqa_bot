"""The record of the last lookup a follow-up turn starts from, such as "cheaper" or "the second one"."""

from __future__ import annotations

from typing import Any

from agent.memory.session.search_results import summarize_search_results
from agent.schemas.routes import Assumptions, DomainRoute, LastNeedDb, QueryRoute

_INTENT_SUMMARY_CHARS = 240


def build_last_search(
    *,
    message: str,
    query: QueryRoute,
    domain: DomainRoute,
    assumptions: Assumptions | None,
    rows: list[dict[str, Any]],
    sql_result: dict[str, Any],
    listing_ids: list[str],
) -> LastNeedDb:
    """What was asked, which domains answered it, and a summary of what came back."""
    result_meta = assumptions.model_dump() if assumptions else {}
    if rows:
        result_meta.update(summarize_search_results(rows))
    if sql_result:
        result_meta["row_count"] = sql_result.get(
            "row_count", result_meta.get("row_count")
        )
        result_meta["truncated"] = bool(sql_result.get("truncated"))
    if listing_ids:
        result_meta["ids"] = listing_ids
    # A refine starts from these, so "cheaper" keeps the place and the filters.
    if query.names:
        result_meta["names"] = [name.model_dump(mode="json") for name in query.names]
    if query.listing_filters is not None:
        result_meta["listing_filters"] = query.listing_filters.model_dump(
            mode="json", exclude_defaults=True
        )
    return LastNeedDb(
        domain_ids=list(domain.domain_ids),
        join_ids=list(domain.join_ids),
        intent_summary=message.strip()[:_INTENT_SUMMARY_CHARS],
        result_meta=result_meta,
    )
