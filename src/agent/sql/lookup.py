"""Answer a lookup from the warehouse.

Property searches are written in code from the router's filters (`run_listing_lookup`).
Everything else is drafted by the model from the loaded catalog and the grounded names,
run, and retried once (`run_sql_lookup`).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from langchain_core.runnables import RunnableConfig

from agent.enums.routing import Intent
from catalog import date_coverage
from agent.schemas.grounding import Grounding, as_grounding
from agent.schemas.listing import ListingFilters, MentionKind
from agent.schemas.routes import QueryRoute, as_assumptions, as_domain_route, as_query_route
from agent.schemas.sql import SqlDraft
from agent.sql.execute import SqlFailed, SqlPage
from agent.sql.guard import SqlRejected, applied_conditions, prepare_select, referenced_tables, tables_in_domains
from agent.sql.listing_rules import LISTINGS_TABLE
from agent.sql.listing_search import ListingSearch, search_listings
from agent.sql.listings import is_listing_list, listing_ids_from
from agent.sql.trace import trace_sql_attempt
from agent.states.chat import ChatState
from common.logger import get_logger
from common.schemas.pagination import page_request
from config import ActiveConfig

logger = get_logger("agent.sql")

MAX_ATTEMPTS = 2
EMPTY_LOOKUP_REPLY = "Nothing matched those filters. I can widen the area or the dates if you want."
FAILED_LOOKUP_REPLY = "I couldn't complete that lookup. Try a more specific area or time range."
NO_ROWS = "The query returned no rows."
ONLY_ZERO_VALUES = (
    "The query returned one row whose values are all zero or empty. A name filter probably matched "
    "nothing; use the stored values in resolved_names, or check the filters against the catalog."
)
LISTING_INTENTS = frozenset({Intent.LIST, Intent.RANK})


def uses_listing_search(state: ChatState) -> bool:
    """The user wants to see properties on the market. Written in code, not by the model.

    The router's listing filters decide this, not which catalog packs were loaded.
    """
    query = as_query_route(state.get("query_route"))
    return query is not None and query.listing_filters is not None and query.intent in LISTING_INTENTS


def run_listing_lookup(state: ChatState, runner, *, client=None) -> dict:
    """Search live listings from the router's filters and the grounded names. No model call."""
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    domain_ids = [*domain.domain_ids, *domain.join_ids] if domain is not None else []
    grounding = as_grounding(state.get("grounding")) or Grounding()
    assumptions = as_assumptions(state.get("assumptions"))
    window = page_request(
        page=(assumptions.page if assumptions and assumptions.page else 1),
        per_page=assumptions.limit if assumptions else None,
    )
    search = _listing_search(query, grounding)
    try:
        found = search_listings(
            search,
            runner,
            limit=window.per_page,
            offset=(window.page - 1) * window.per_page,
        )
    except SqlFailed as exc:
        last = _result(
            domain_ids=domain_ids,
            attempt=1,
            purpose="property search",
            sql="",
            status="failed",
            error=str(exc),
        )
        trace_sql_attempt(last, client)
        return {"sql_result": last, "sql_rows": [], "listing_ids": []}
    rows = [{"property_id": listing_id} for listing_id in found.ids]
    last = _result(
        domain_ids=domain_ids,
        attempt=1,
        purpose="property search",
        sql=found.query.sql,
        status="rows" if rows else "empty",
        columns=["property_id"],
        rows=rows,
        duration_ms=found.duration_ms,
        error=None if rows else NO_ROWS,
    )
    last.update(
        params=found.query.params,
        total=found.total,
        notes=[*grounding.notes(), *found.notes],
        filters=_listing_conditions(search),
    )
    trace_sql_attempt(last, client)
    return {"sql_result": last, "sql_rows": rows, "listing_ids": found.ids}


def run_sql_lookup(
    state: ChatState,
    models,
    runner,
    *,
    config: RunnableConfig | None = None,
    client=None,
    row_cap: int | None = None,
) -> dict:
    """Return `sql_result` and `sql_rows` for the answer node. At most two attempts."""
    domain = as_domain_route(state.get("domain_route"))
    domain_ids = [*domain.domain_ids, *domain.join_ids] if domain is not None else []
    allowed = tables_in_domains(domain_ids)
    cap = ActiveConfig.SQL_ROW_CAP if row_cap is None else row_cap
    assumptions = as_assumptions(state.get("assumptions"))
    frame = _frame_for_prompt(state.get("query_frame"))
    catalog = state.get("catalog_context") or ""
    message = _message(state)
    history = _history(state)

    listing_ids_only = is_listing_list(state)
    grounding = as_grounding(state.get("grounding"))
    resolved_names = grounding.for_sql_prompt() if grounding and grounding.names else None
    previous_error: str | None = None
    last: dict[str, Any] = _empty_result(domain_ids)
    # An attempt that returned rows, kept in case the retry it prompted fails outright.
    answered: dict[str, Any] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        draft = _draft(
            models,
            message=message,
            history=history,
            catalog=catalog,
            allowed_tables=sorted(allowed),
            assumptions=assumptions.model_dump() if assumptions else None,
            query_frame=frame,
            previous_error=previous_error,
            listing_ids_only=listing_ids_only,
            resolved_names=resolved_names,
            config=config,
        )
        logger.info(
            "sql.generate",
            extra={
                "extra_data": {
                    "attempt": attempt,
                    "purpose": draft.purpose,
                    "sql": draft.sql,
                    "domain_ids": domain_ids,
                }
            },
        )
        try:
            guarded = prepare_select(draft.sql, allowed, cap)
        except SqlRejected as exc:
            last = _result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=draft.sql,
                status="failed",
                error=str(exc),
            )
            trace_sql_attempt(last, client)
            previous_error = str(exc)
            continue
        try:
            page = runner(guarded)
        except SqlFailed as exc:
            last = _result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=guarded,
                status="failed",
                error=str(exc),
            )
            trace_sql_attempt(last, client)
            previous_error = str(exc)
            continue
        if not isinstance(page, SqlPage):
            page = SqlPage(
                columns=list(getattr(page, "columns", []) or []),
                rows=list(getattr(page, "rows", []) or []),
                truncated=bool(getattr(page, "truncated", False)),
                duration_ms=int(getattr(page, "duration_ms", 0) or 0),
            )
        status = "rows" if page.rows else "empty"
        last = _result(
            domain_ids=domain_ids,
            attempt=attempt,
            purpose=draft.purpose,
            sql=guarded,
            status=status,
            columns=page.columns,
            rows=page.rows,
            truncated=page.truncated,
            duration_ms=page.duration_ms,
            error=None if page.rows else NO_ROWS,
        )
        last["filters"] = applied_conditions(guarded)
        last["coverage"] = date_coverage(referenced_tables(guarded))
        if grounding is not None:
            last["notes"] = grounding.notes()
        trace_sql_attempt(last, client)
        if page.rows:
            answered = last
        retry_reason = NO_ROWS if not page.rows else ONLY_ZERO_VALUES if _only_zero_values(page.rows) else None
        if retry_reason is None or attempt == MAX_ATTEMPTS:
            break
        previous_error = retry_reason

    if last["status"] == "failed" and answered is not None:
        last = answered
    rows = list(last["rows"]) if last["status"] == "rows" else []
    return {
        "sql_result": last,
        "sql_rows": rows,
        "listing_ids": listing_ids_from(state, rows),
    }


def _listing_search(query: QueryRoute | None, grounding: Grounding) -> ListingSearch:
    places = [name for name in grounding.names if name.kind is MentionKind.PLACE]
    filters = query.listing_filters if query is not None else None
    return ListingSearch(
        filters=filters or ListingFilters(),
        places=[name.place for name in places if name.place is not None],
        developers=grounding.stored_in(LISTINGS_TABLE, "developer"),
        unmatched_places=[name.text for name in places if name.place is None],
    )


def _listing_conditions(search: ListingSearch) -> list[str]:
    """The user's own listing filters, as `field: value`, for the reply to name."""
    stated = search.filters.model_dump(mode="json", exclude_defaults=True)
    conditions = [f"{field}: {value}" for field, value in stated.items() if value not in (None, [], "")]
    conditions.extend(f"place: {place.title}" for place in search.places)
    conditions.extend(f"place text: {text}" for text in search.unmatched_places)
    conditions.extend(f"developer: {name}" for name in search.developers)
    return conditions


def _only_zero_values(rows: list[dict]) -> bool:
    """One row of nothing but zeros and nulls: an aggregate whose filter matched no rows."""
    if len(rows) != 1 or not rows[0]:
        return False
    return all(_is_zero_or_empty(value) for value in rows[0].values())


def _is_zero_or_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def _draft(models, **kwargs) -> SqlDraft:
    parsed = models.draft_sql(**kwargs)
    if isinstance(parsed, SqlDraft):
        return parsed
    return SqlDraft.model_validate(parsed)


def _frame_for_prompt(frame: dict | None) -> dict | None:
    if not frame:
        return None
    safe = {key: value for key, value in frame.items() if key != "sql"}
    return safe or None


def _message(state: ChatState) -> str:
    from agent.services.transcript import latest_user_text

    return latest_user_text(state.get("messages") or [])


def _history(state: ChatState) -> str:
    from agent.services.transcript import ANSWER_HISTORY, history_summary

    return history_summary(state.get("messages") or [], limit=ANSWER_HISTORY)


def _empty_result(domain_ids: list[str]) -> dict[str, Any]:
    return _result(domain_ids=domain_ids, attempt=0, purpose="", sql="", status="failed", error="SQL was not drafted")


def _result(
    *,
    domain_ids: list[str],
    attempt: int,
    purpose: str,
    sql: str,
    status: str,
    columns: list[str] | None = None,
    rows: list[dict] | None = None,
    truncated: bool = False,
    duration_ms: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    visible = list(rows or [])
    return {
        "status": status,
        "purpose": purpose,
        "sql": sql,
        "domain_ids": list(domain_ids),
        "attempt": attempt,
        "columns": list(columns or []),
        "rows": visible,
        "row_count": len(visible),
        "truncated": truncated,
        "duration_ms": duration_ms,
        "error": error,
    }
