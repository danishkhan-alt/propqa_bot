"""Graph nodes that write the reply: direct answers, lookup answers, and the fallback."""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.enums.routing import Route
from agent.graph.nodes.runtime import models_for
from agent.reply.buyer_profile import pick_next_profile_question
from agent.reply.data_sources import FOCUSED_LISTINGS_DATA_NOTE, describe_data_sources
from agent.reply.place_map import split_place_rows
from agent.reply.streaming import publish_structured_reply, stream_memory_notes, stream_prose_reply
from agent.schemas.profile import ProfileQuestion
from agent.schemas.routes import (
    QueryRoute,
    as_assumptions,
    as_domain_route,
    as_query_route,
)
from agent.services.stream_events import publish_stream_event
from agent.services.transcript import (
    ANSWER_HISTORY_MESSAGE_LIMIT,
    format_recent_history,
    latest_user_text,
)
from agent.sql.cards import PROMPT_LISTING_LIMIT, prompt_listing_facts
from agent.sql.lookup import EMPTY_LOOKUP_REPLY, FAILED_LOOKUP_REPLY
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.reply")

MISSING_LISTINGS_REPLY = (
    "I couldn't find the listings you selected. They may have been taken off the market. "
    "Remove them from the chat and pick another listing to ask about."
)
OUT_OF_SCOPE_REPLY = (
    "I can only help with Dubai property: buying, renting, prices, areas, projects, and listings. "
    'Try something like "average rent for a 2-bed in JVC" or "apartments for sale in Dubai Marina under AED 2M".'
)
FAILED_FOCUSED_LISTINGS_REPLY ="I couldn't put the details of those listings together just now. Could you ask me again?"


def write_reply(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    query = as_query_route(state.get("query_route"))
    messages = state.get("messages") or []
    message = latest_user_text(messages)
    if state.get("focused_property_ids"):
        return _reply_about_focused_listings(state, runtime, message, messages, config)
    if query is None:
        return _reply_without_data(state, runtime, message, messages, config)

    if query.route is Route.OUT_OF_SCOPE:
        # Fixed text: a model asked to decline tends to answer a little first, and this costs nothing.
        publish_stream_event("text", delta=OUT_OF_SCOPE_REPLY)
        text = _stream_memory_notes(OUT_OF_SCOPE_REPLY, state)
        return {"messages": [AIMessage(content=text)], "awaiting_sql": False}

    if query.route is Route.DIRECT_ANSWER:
        question = _next_profile_question(state, query, has_listings=False)
        structured = publish_structured_reply(
            models_for(runtime),
            message=message,
            messages=messages,
            memory_block=state.get("memory_block") or "",
            session_profile=state.get("session_profile") or {},
            question=question,
            config=config,
        )
        if structured is None:
            text = stream_prose_reply(
                models_for(runtime),
                "answer_direct",
                message=message,
                history=format_recent_history(messages, limit=ANSWER_HISTORY_MESSAGE_LIMIT),
                memory_block=state.get("memory_block") or "",
                config=config,
            )
        else:
            text = structured
        text = _stream_memory_notes(text, state)
        return _reply_state_update(state, text, question if structured is not None else None)

    domain = as_domain_route(state.get("domain_route"))
    if domain is None or not domain.domain_ids:
        return _reply_without_data(state, runtime, message, messages, config)

    return _reply_from_lookup_results(state, runtime, message, messages, config)


def _reply_from_lookup_results(
    state: ChatState,
    runtime: Runtime[AgentContext],
    message: str,
    messages: list,
    config: RunnableConfig,
) -> dict:
    result = state.get("sql_result") or {}
    status = result.get("status")
    query = as_query_route(state.get("query_route"))
    assumptions = as_assumptions(state.get("assumptions"))
    listing_ids = [
        str(item) for item in (state.get("listing_ids") or []) if str(item).strip()
    ]
    # A listing turn answers from the filled cards. Rows stay only for columns the cards
    # lack, such as a permit number, and only for the listings the model reads.
    listings = (
        prompt_listing_facts(list(state.get("listing_cards") or [])) if listing_ids else []
    )
    rows = list(result.get("rows") or [])
    columns = list(result.get("columns") or [])
    map_pins: list[dict] = []
    if listing_ids:
        if len(columns) <= 1:
            rows, columns = [], []
        else:
            rows = rows[:PROMPT_LISTING_LIMIT]
    else:
        rows, columns, map_pins = split_place_rows(rows, columns)
    note = describe_data_sources(result.get("domain_ids") or [])
    search_notes = [str(item) for item in (result.get("notes") or [])]
    filters = [str(item) for item in (result.get("filters") or [])]
    coverage = list(result.get("coverage") or [])
    listing_count = int(result.get("total") or len(listing_ids))
    question = None
    structured = None
    if status in ("rows", "empty"):
        question = _next_profile_question(state, query, has_listings=bool(listing_ids))
        structured = publish_structured_reply(
            models_for(runtime),
            message=message,
            messages=messages,
            rows=rows,
            columns=columns,
            row_count=int(result.get("row_count") or 0),
            truncated=bool(result.get("truncated")),
            purpose=str(result.get("purpose") or ""),
            assumptions=assumptions.model_dump() if assumptions else None,
            memory_block=state.get("memory_block") or "",
            listings=listings,
            listing_count=listing_count,
            lookup_status=status,
            data_note=note,
            search_notes=search_notes,
            filters=filters,
            coverage=coverage,
            session_profile=state.get("session_profile") or {},
            question=question,
            config=config,
            map_pins=map_pins,
        )
    if structured is not None:
        text = structured
    elif status == "rows":
        text = stream_prose_reply(
            models_for(runtime),
            "answer_from_sql",
            message=message,
            history=format_recent_history(messages, limit=ANSWER_HISTORY_MESSAGE_LIMIT),
            rows=listings or rows,
            columns=columns,
            row_count=int(result.get("row_count") or 0),
            truncated=bool(result.get("truncated")),
            purpose=str(result.get("purpose") or ""),
            assumptions=assumptions.model_dump() if assumptions else None,
            memory_block=state.get("memory_block") or "",
            listing_ids=listing_ids or None,
            data_note=note,
            search_notes=search_notes,
            filters=filters,
            coverage=coverage,
            config=config,
        )
    elif status == "empty":
        text = EMPTY_LOOKUP_REPLY
        publish_stream_event("text", delta=text)
    else:
        text = FAILED_LOOKUP_REPLY
        publish_stream_event("text", delta=text)
    text = _stream_memory_notes(text, state)
    logger.info(
        "answer.synthesize",
        extra={
            "extra_data": {
                "status": status,
                "row_count": result.get("row_count"),
                "truncated": result.get("truncated"),
                "columns": result.get("columns"),
                "listing_facts": len(listings),
                "map_pins": len(map_pins),
                "question": (
                    question.id if question and structured is not None else None
                ),
                "user_id": runtime.context.user_id,
            }
        },
    )
    return _reply_state_update(state, text, question if structured is not None else None)


def _reply_about_focused_listings(
    state: ChatState,
    runtime: Runtime[AgentContext],
    message: str,
    messages: list,
    config: RunnableConfig,
) -> dict:
    """Answer from the full advert of each listing the user picked. Photo cards are already on screen."""
    listings = list(state.get("focused_listings") or [])
    structured = None
    if listings:
        structured = publish_structured_reply(
            models_for(runtime),
            method_name="draft_listing_reply",
            message=message,
            messages=messages,
            listings=listings,
            memory_block=state.get("memory_block") or "",
            data_note=FOCUSED_LISTINGS_DATA_NOTE,
            session_profile=state.get("session_profile") or {},
            question=None,
            config=config,
            map_pins=list(state.get("focused_map_pins") or []),
        )
    if structured is not None:
        text = structured
    else:
        text = FAILED_FOCUSED_LISTINGS_REPLY if listings else MISSING_LISTINGS_REPLY
        publish_stream_event("text", delta=text)
    logger.info(
        "answer.focus",
        extra={
            "extra_data": {
                "listings": len(listings),
                "structured": structured is not None,
                "user_id": runtime.context.user_id,
            }
        },
    )
    return _reply_state_update(state, text, None)


def _reply_without_data(
    state: ChatState,
    runtime: Runtime[AgentContext],
    message: str,
    messages: list,
    config: RunnableConfig,
) -> dict:
    text = stream_prose_reply(
        models_for(runtime),
        "answer_unavailable",
        message=message,
        history=format_recent_history(messages, limit=ANSWER_HISTORY_MESSAGE_LIMIT),
        config=config,
    )
    text = _stream_memory_notes(text, state)
    return {"messages": [AIMessage(content=text)], "awaiting_sql": False}


def _stream_memory_notes(text: str, state: ChatState) -> str:
    return stream_memory_notes(
        text, state.get("disclosure") or "", state.get("memory_question") or ""
    )


def _next_profile_question(
    state: ChatState, query: QueryRoute | None, *, has_listings: bool
) -> ProfileQuestion | None:
    return pick_next_profile_question(
        query,
        state.get("session_profile") or {},
        state.get("profile_asked"),
        has_listings=has_listings,
    )


def _reply_state_update(state: ChatState, text: str, question: ProfileQuestion | None) -> dict:
    """Store the question with the reply, so history reads the way the user saw it."""
    content = f"{text}\n\n{question.prompt}" if question is not None else text
    update: dict = {"messages": [AIMessage(content=content)], "awaiting_sql": False}
    if question is not None:
        update["profile_asked"] = [*(state.get("profile_asked") or []), question.id]
    return update
