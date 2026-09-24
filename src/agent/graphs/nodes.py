from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext, RouterModels
from agent.enums.routing import Intent, Route, TurnKind
from agent.schemas.routes import (
    Assumptions,
    DomainRoute,
    LastNeedDb,
    QueryRoute,
    as_assumptions,
    as_domain_route,
    as_last_need_db,
    as_query_route,
)
from agent.reply.clarify import Question, merge_profile, next_question
from agent.schemas.reply import StructuredReply
from agent.services.catalog_index import (
    domain_blurbs,
    domain_index_text,
    render_catalog,
    table_count,
)
from agent.services.events import publish
from agent.services.llm import default_models
from agent.graphs.memory import persist_working, read_context
from agent.memory.read.prompt_text import append_memory_notes
from agent.memory.session.search_results import summarize_search_results
from agent.services.transcript import ANSWER_HISTORY, history_summary, latest_user_text
from agent.sql.cards import listing_facts
from agent.sql.lookup import EMPTY_LOOKUP_REPLY, FAILED_LOOKUP_REPLY
from agent.states.chat import ChatState
from agent.validator import apply_query_policy, sanitize_domain_route
from common.logger import get_logger
from common.schemas.pagination import page_request

logger = get_logger("agent.router")

# Row results share one page window. An average or a single lookup does not.
_PAGED = frozenset({Intent.LIST, Intent.RANK})

def load_context(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    update = {"user_id": runtime.context.user_id}
    update.update(read_context(runtime, config))
    return update


def query_router(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    messages = state.get("messages") or []
    message = latest_user_text(messages)
    last = as_last_need_db(state.get("last_need_db"))
    route = _models(runtime).route_query(
        message=message,
        history=history_summary(messages),
        last_need_db=last,
        domain_blurbs=domain_blurbs(),
        memory_context=state.get("memory_block") or "",
        config=config,
    )
    route, notes = apply_query_policy(route, last)

    logger.info(
        "router.query",
        extra={
            "extra_data": {
                "route": route.route.value,
                "turn_kind": route.turn_kind.value,
                "intent": route.intent.value,
                "purpose": route.purpose,
                "limit": route.limit,
                "order": route.order,
                "confidence": route.confidence,
                "rationale": route.rationale,
                "notes": notes,
                "user_id": runtime.context.user_id,
            }
        },
    )
    assumptions = None
    if route.route is Route.NEED_DB:
        assumptions = _assumptions(route)
    update: dict = {
        "query_route": route,
        "assumptions": assumptions,
        "session_profile": merge_profile(state.get("session_profile"), route.profile),
    }
    if route.route is not Route.NEED_DB:
        update["domain_route"] = None
        update["awaiting_sql"] = False
    return update


def domain_router(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    messages = state.get("messages") or []
    message = latest_user_text(messages)
    query = as_query_route(state.get("query_route"))
    last = as_last_need_db(state.get("last_need_db"))
    if query is None:
        raise RuntimeError("domain router ran without a query route")

    kind = query.turn_kind
    notes: list[str] = []
    if kind is TurnKind.REFINE and last is not None:
        route = DomainRoute(
            domain_ids=list(last.domain_ids),
            join_ids=list(last.join_ids),
            confidence=1.0,
            rationale="Reused domains from the previous lookup.",
        )
        notes.append("reused")
    else:
        route = _models(runtime).route_domain(
            message=message,
            turn_kind=kind,
            last_need_db=last,
            index_text=domain_index_text(),
            config=config,
        )

    route, sanitize_notes = sanitize_domain_route(route)
    notes.extend(sanitize_notes)
    logger.info(
        "router.domain",
        extra={
            "extra_data": {
                "domain_ids": route.domain_ids,
                "join_ids": route.join_ids,
                "confidence": route.confidence,
                "rationale": route.rationale,
                "notes": notes,
                "user_id": runtime.context.user_id,
            }
        },
    )
    return {"query_route": query, "domain_route": route}


def catalog_load(state: ChatState) -> dict:
    domain = as_domain_route(state.get("domain_route"))
    if domain is None:
        return {"catalog_context": "", "loaded_domains": []}
    loaded = [*domain.domain_ids, *domain.join_ids]
    context = render_catalog(domain.domain_ids, domain.join_ids)
    logger.info(
        "catalog.load",
        extra={
            "extra_data": {
                "domain_ids": domain.domain_ids,
                "join_ids": domain.join_ids,
                "table_count": table_count(loaded),
            }
        },
    )
    return {"catalog_context": context, "loaded_domains": loaded}


def answer(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    query = as_query_route(state.get("query_route"))
    messages = state.get("messages") or []
    message = latest_user_text(messages)
    if query is None:
        return _unavailable(state, runtime, message, messages, config)

    if query.route is Route.DIRECT_ANSWER:
        question = _question(state, query, has_listings=False)
        structured = _draft_structured(
            _models(runtime),
            message=message,
            messages=messages,
            memory_block=state.get("memory_block") or "",
            session_profile=state.get("session_profile") or {},
            question=question,
            config=config,
        )
        if structured is None:
            text = _speak(
                _models(runtime),
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


def finalize(state: ChatState, config: RunnableConfig) -> dict:
    """Drop catalog YAML so the checkpointer does not keep schema packs."""
    update: dict = {"catalog_context": "", "loaded_domains": [], "listing_ids": [], "listing_cards": []}
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    if (
        query is not None
        and query.route is Route.NEED_DB
        and domain is not None
        and domain.domain_ids
    ):
        message = latest_user_text(state.get("messages") or [])
        assumptions = as_assumptions(state.get("assumptions"))
        rows = list(state.get("sql_rows") or [])
        sql_result = state.get("sql_result") or {}
        meta = assumptions.model_dump() if assumptions else {}
        if rows:
            meta.update(summarize_search_results(rows))
        if sql_result:
            meta["row_count"] = sql_result.get("row_count", meta.get("row_count"))
            meta["truncated"] = bool(sql_result.get("truncated"))
        listing_ids = [str(item) for item in (state.get("listing_ids") or []) if str(item).strip()]
        if listing_ids:
            meta["ids"] = listing_ids
        update["last_need_db"] = LastNeedDb(
            domain_ids=list(domain.domain_ids),
            join_ids=list(domain.join_ids),
            intent_summary=message.strip()[:240],
            result_meta=meta,
        )
        update["awaiting_sql"] = False
        update["sql_result"] = None
        logger.info(
            "catalog.unload",
            extra={
                "extra_data": {
                    "domain_ids": domain.domain_ids,
                    "join_ids": domain.join_ids,
                }
            },
        )
    else:
        update["awaiting_sql"] = False
    update.update(persist_working({**state, **update}, config))
    return update


def route_after_query(state: ChatState) -> str:
    query = as_query_route(state.get("query_route"))
    if query is not None and query.route is Route.NEED_DB:
        return "domain_router"
    return "answer"


def route_after_domain(state: ChatState) -> str:
    domain = as_domain_route(state.get("domain_route"))
    if domain is not None and domain.domain_ids:
        return "apply_defaults"
    return "answer"


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
    listing_ids = [str(item) for item in (state.get("listing_ids") or []) if str(item).strip()]
    # A listing turn answers from the filled cards, not from the id-only SQL rows.
    listings = listing_facts(list(state.get("listing_cards") or [])) if listing_ids else []
    rows = [] if listing_ids else list(result.get("rows") or [])
    columns = [] if listing_ids else list(result.get("columns") or [])
    note = _data_note(result.get("domain_ids") or [])
    question = None
    structured = None
    if status in ("rows", "empty"):
        question = _question(state, query, has_listings=bool(listing_ids))
        structured = _draft_structured(
            _models(runtime),
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
            listing_count=len(listing_ids),
            lookup_status=status,
            data_note=note,
            session_profile=state.get("session_profile") or {},
            question=question,
            config=config,
        )
    if structured is not None:
        text = structured
    elif status == "rows":
        text = _speak(
            _models(runtime),
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
                "question": question.id if question and structured is not None else None,
                "user_id": runtime.context.user_id,
            }
        },
    )
    return _reply_update(state, text, question if structured is not None else None)


def _unavailable(
    state: ChatState,
    runtime: Runtime[AgentContext],
    message: str,
    messages: list,
    config: RunnableConfig,
) -> dict:
    text = _speak(
        _models(runtime),
        "answer_unavailable",
        message=message,
        history=history_summary(messages, limit=ANSWER_HISTORY),
        config=config,
    )
    text = _with_memory_notes(text, state)
    return {"messages": [AIMessage(content=text)], "awaiting_sql": False}


def _assumptions(route: QueryRoute) -> Assumptions:
    """Keep the model's purpose and order. Page a list with the shared window."""
    if route.intent not in _PAGED:
        return Assumptions(purpose=route.purpose, limit=route.limit, order=route.order)
    window = page_request(per_page=route.limit)
    return Assumptions(
        purpose=route.purpose,
        limit=window.per_page,
        order=route.order,
        page=window.page,
    )


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
    noted = append_memory_notes(text, state.get("disclosure") or "", state.get("memory_question") or "")
    extra = noted[len(text):] if noted.startswith(text) else ""
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


def _question(state: ChatState, query: QueryRoute | None, *, has_listings: bool) -> Question | None:
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
    message: str,
    messages: list,
    session_profile: dict,
    question: Question | None,
    config: RunnableConfig,
    **fields,
) -> str | None:
    """Stream a structured reply when the model supports it. Otherwise the caller streams prose."""
    draft = getattr(models, "draft_reply", None)
    if not callable(draft):
        return None
    try:
        parsed = draft(
            message=message,
            history=history_summary(messages, limit=ANSWER_HISTORY),
            session_profile=session_profile,
            follow_up_question=question.prompt if question is not None else None,
            on_text=lambda delta: publish("text", delta=delta),
            config=config,
            **fields,
        )
    except Exception:
        logger.warning("answer.structured failed", exc_info=True)
        return None
    reply = parsed if isinstance(parsed, StructuredReply) else StructuredReply.model_validate(parsed)
    payload = reply.model_dump()
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


def _models(runtime: Runtime[AgentContext]) -> RouterModels:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    if runtime.context.models is not None:
        return runtime.context.models
    return default_models()
