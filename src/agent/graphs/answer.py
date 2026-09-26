"""Graph nodes that write the reply: direct answers, lookup answers, and the fallback."""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext, RouterModels
from agent.enums.routing import Route
from agent.graphs.runtime import models_for
from agent.memory.read.prompt_text import append_memory_notes
from agent.reply.clarify import Question, next_question
from agent.reply.figures import reply_blocks
from agent.schemas.reply import StructuredReply
from agent.schemas.routes import (
    QueryRoute,
    as_assumptions,
    as_domain_route,
    as_query_route,
)
from agent.services.events import publish
from agent.services.transcript import ANSWER_HISTORY, history_summary, latest_user_text
from agent.sql.cards import PROMPT_LISTING_LIMIT, listing_facts
from agent.sql.lookup import EMPTY_LOOKUP_REPLY, FAILED_LOOKUP_REPLY
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.router")

FOCUS_DATA_NOTE = "the listing's advert and nearby places"
MISSING_LISTINGS_REPLY = (
    "I couldn't find the listings you selected. They may have been taken off the market. "
    "Remove them from the chat and pick another listing to ask about."
)
FAILED_FOCUS_REPLY = "I couldn't put the details of those listings together just now. Could you ask me again?"


def answer(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    query = as_query_route(state.get("query_route"))
    messages = state.get("messages") or []
    message = latest_user_text(messages)
    if state.get("focused_property_ids"):
        return _answer_about_listings(state, runtime, message, messages, config)
    if query is None:
        return _unavailable(state, runtime, message, messages, config)

    if query.route is Route.DIRECT_ANSWER:
        question = _question(state, query, has_listings=False)
        structured = _draft_structured(
            models_for(runtime),
            message=message,
            messages=messages,
            memory_block=state.get("memory_block") or "",
            session_profile=state.get("session_profile") or {},
            question=question,
            config=config,
        )
        if structured is None:
            text = _speak(
                models_for(runtime),
                "answer_direct",
                message=message,
                history=history_summary(messages, limit=ANSWER_HISTORY),
                memory_block=state.get("memory_block") or "",
                config=config,
            )
        else:
            text = structured
        text = _with_memory_notes(text, state)
        return _reply_update(state, text, question if structured is not None else None)

    domain = as_domain_route(state.get("domain_route"))
    if domain is None or not domain.domain_ids:
        return _unavailable(state, runtime, message, messages, config)

    return _answer_from_lookup(state, runtime, message, messages, config)


def _answer_from_lookup(
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
        listing_facts(list(state.get("listing_cards") or [])) if listing_ids else []
    )
    rows = list(result.get("rows") or [])
    columns = list(result.get("columns") or [])
    if listing_ids:
        if len(columns) <= 1:
            rows, columns = [], []
        else:
            rows = rows[:PROMPT_LISTING_LIMIT]
    note = _data_note(result.get("domain_ids") or [])
    search_notes = [str(item) for item in (result.get("notes") or [])]
    filters = [str(item) for item in (result.get("filters") or [])]
    coverage = list(result.get("coverage") or [])
    listing_count = int(result.get("total") or len(listing_ids))
    question = None
    structured = None
    if status in ("rows", "empty"):
        question = _question(state, query, has_listings=bool(listing_ids))
        structured = _draft_structured(
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
        )
    if structured is not None:
        text = structured
    elif status == "rows":
        text = _speak(
            models_for(runtime),
            "answer_from_sql",
            message=message,
            history=history_summary(messages, limit=ANSWER_HISTORY),
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
        publish("text", delta=text)
    else:
        text = FAILED_LOOKUP_REPLY
        publish("text", delta=text)
    text = _with_memory_notes(text, state)
    logger.info(
        "answer.synthesize",
        extra={
            "extra_data": {
                "status": status,
                "row_count": result.get("row_count"),
                "truncated": result.get("truncated"),
                "columns": result.get("columns"),
                "listing_facts": len(listings),
                "question": (
                    question.id if question and structured is not None else None
                ),
                "user_id": runtime.context.user_id,
            }
        },
    )
    return _reply_update(state, text, question if structured is not None else None)


def _answer_about_listings(
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
        structured = _draft_structured(
            models_for(runtime),
            method="draft_listing_reply",
            message=message,
            messages=messages,
            listings=listings,
            memory_block=state.get("memory_block") or "",
            data_note=FOCUS_DATA_NOTE,
            session_profile=state.get("session_profile") or {},
            question=None,
            config=config,
        )
    if structured is not None:
        text = structured
    else:
        text = FAILED_FOCUS_REPLY if listings else MISSING_LISTINGS_REPLY
        publish("text", delta=text)
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
    return _reply_update(state, text, None)


def _unavailable(
    state: ChatState,
    runtime: Runtime[AgentContext],
    message: str,
    messages: list,
    config: RunnableConfig,
) -> dict:
    text = _speak(
        models_for(runtime),
        "answer_unavailable",
        message=message,
        history=history_summary(messages, limit=ANSWER_HISTORY),
        config=config,
    )
    text = _with_memory_notes(text, state)
    return {"messages": [AIMessage(content=text)], "awaiting_sql": False}


def _speak(models: RouterModels, name: str, **kwargs) -> str:
    """Stream each text piece as the model produces it, and return the reply."""
    stream = getattr(models, f"stream_{name}", None)
    if callable(stream):
        parts: list[str] = []
        for delta in stream(**kwargs):
            piece = delta if isinstance(delta, str) else str(delta or "")
            if not piece:
                continue
            parts.append(piece)
            publish("text", delta=piece)
        return "".join(parts).strip()
    text = str(getattr(models, name)(**kwargs) or "").strip()
    if text:
        publish("text", delta=text)
    return text


def _with_memory_notes(text: str, state: ChatState) -> str:
    noted = append_memory_notes(
        text, state.get("disclosure") or "", state.get("memory_question") or ""
    )
    extra = noted[len(text) :] if noted.startswith(text) else ""
    if extra.strip():
        publish("text", delta=extra)
    return noted


_SOURCE_PHRASES = {
    "listings": "live asking prices and registered property records",
    "transactions": "registered sales and rent contracts",
    "market": "official price indices and community averages",
    "regulations": "owners-association service charges",
    "developers": "project and developer records",
    "schools": "school ratings and fees",
    "amenities": "parks, healthcare, and building amenities",
    "rta": "metro, roads, and parking",
    "agencies": "licensed brokers and offices",
    "locations": "community records",
}


def _data_note(domain_ids: list) -> str:
    phrases: list[str] = []
    for domain_id in domain_ids:
        phrase = _SOURCE_PHRASES.get(str(domain_id))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return "; ".join(phrases)


def _question(
    state: ChatState, query: QueryRoute | None, *, has_listings: bool
) -> Question | None:
    return next_question(
        query,
        state.get("session_profile") or {},
        state.get("profile_asked"),
        has_listings=has_listings,
    )


def _reply_update(state: ChatState, text: str, question: Question | None) -> dict:
    """Store the question with the reply, so history reads the way the user saw it."""
    content = f"{text}\n\n{question.prompt}" if question is not None else text
    update: dict = {"messages": [AIMessage(content=content)], "awaiting_sql": False}
    if question is not None:
        update["profile_asked"] = [*(state.get("profile_asked") or []), question.id]
    return update


def _draft_structured(
    models: RouterModels,
    *,
    method: str = "draft_reply",
    message: str,
    messages: list,
    session_profile: dict,
    question: Question | None,
    config: RunnableConfig,
    **fields,
) -> str | None:
    """Stream a structured reply when the model supports it. Otherwise the caller streams prose."""
    draft = getattr(models, method, None)
    if not callable(draft):
        return None
    if question is not None:
        fields["follow_up_question"] = question.prompt
    try:
        parsed = draft(
            message=message,
            history=history_summary(messages, limit=ANSWER_HISTORY),
            session_profile=session_profile,
            on_text=lambda delta: publish("text", delta=delta),
            config=config,
            **fields,
        )
    except Exception:
        logger.warning("answer.structured failed", exc_info=True)
        return None
    reply = (
        parsed
        if isinstance(parsed, StructuredReply)
        else StructuredReply.model_validate(parsed)
    )
    payload = reply.model_dump()
    # Listings have their own photo cards, so their rows are never laid out as figures.
    figure_rows = [] if fields.get("listings") else list(fields.get("rows") or [])
    payload.update(reply_blocks(reply, figure_rows, list(fields.get("columns") or [])))
    payload["question"] = question.payload() if question is not None else None
    if question is not None:
        # The question already has its own tap options; a chip repeating it is noise.
        asked = question.prompt.casefold()
        payload["suggested_followups"] = [
            item for item in reply.suggested_followups if item.casefold() not in asked
        ]
    note = fields.get("data_note") or ""
    if note and not payload.get("data_source_note"):
        payload["data_source_note"] = note
    payload["session_profile"] = session_profile
    publish("reply", type="reply", reply=payload)
    return reply.intro_text.strip()
