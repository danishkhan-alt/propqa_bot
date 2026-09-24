"""Draft a SELECT from the loaded catalog, run it, and retry once."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agent.schemas.routes import as_assumptions, as_domain_route
from agent.schemas.sql import SqlDraft
from agent.sql.execute import SqlFailed, SqlPage
from agent.sql.guard import SqlRejected, prepare_select, tables_in_domains
from agent.sql.listings import is_listing_list, listing_ids_from
from agent.sql.trace import trace_sql_attempt
from agent.states.chat import ChatState
from common.logger import get_logger
from config import ActiveConfig

logger = get_logger("agent.sql")

MAX_ATTEMPTS = 2
EMPTY_LOOKUP_REPLY = "Nothing matched those filters. I can widen the area or the dates if you want."
FAILED_LOOKUP_REPLY = "I couldn't complete that lookup. Try a more specific area or time range."


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
    previous_error: str | None = None
    last: dict[str, Any] = _empty_result(domain_ids)
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
            error=None if page.rows else "The query returned no rows.",
        )
        trace_sql_attempt(last, client)
        if page.rows or attempt == MAX_ATTEMPTS:
            break
        previous_error = "The query returned no rows."

    rows = list(last["rows"]) if last["status"] == "rows" else []
    return {
        "sql_result": last,
        "sql_rows": rows,
        "listing_ids": listing_ids_from(state, rows),
    }


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
