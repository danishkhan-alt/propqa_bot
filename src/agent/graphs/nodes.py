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
from agent.services.catalog_index import (
    domain_blurbs,
    domain_index_text,
    render_catalog,
    table_count,
)
from agent.services.llm import default_models
from agent.services.transcript import history_summary, latest_user_text
from agent.states.chat import ChatState
from agent.validator import apply_query_policy, sanitize_domain_route
from common.logger import get_logger
from common.schemas.pagination import page_request

logger = get_logger("agent.router")

# Row results share one page window. An average or a single lookup does not.
_PAGED = frozenset({Intent.LIST, Intent.RANK})

def load_context(state: ChatState, runtime: Runtime[AgentContext]) -> dict:
    return {"user_id": runtime.context.user_id}


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
    update: dict = {"query_route": route, "assumptions": assumptions}
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
        return _unavailable(runtime, message, messages, config)

    if query.route is Route.DIRECT_ANSWER:
        text = _models(runtime).answer_direct(
            message=message,
            history=history_summary(messages),
            config=config,
        )
        return {"messages": [AIMessage(content=text)], "awaiting_sql": False}

    domain = as_domain_route(state.get("domain_route"))
    if domain is None or not domain.domain_ids:
        return _unavailable(runtime, message, messages, config)

    # SQL agent will run between catalog_load and this node. Until then, do not invent numbers.
    return {"awaiting_sql": True}


def finalize(state: ChatState) -> dict:
    """Drop catalog YAML so the checkpointer does not keep schema packs."""
    update: dict = {"catalog_context": "", "loaded_domains": []}
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
        update["last_need_db"] = LastNeedDb(
            domain_ids=list(domain.domain_ids),
            join_ids=list(domain.join_ids),
            intent_summary=message.strip()[:240],
            result_meta=assumptions.model_dump() if assumptions else {},
        )
        update["awaiting_sql"] = True
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
    return update


def route_after_query(state: ChatState) -> str:
    query = as_query_route(state.get("query_route"))
    if query is not None and query.route is Route.NEED_DB:
        return "domain_router"
    return "answer"


def route_after_domain(state: ChatState) -> str:
    domain = as_domain_route(state.get("domain_route"))
    if domain is not None and domain.domain_ids:
        return "catalog_load"
    return "answer"


def _unavailable(
    runtime: Runtime[AgentContext],
    message: str,
    messages: list,
    config: RunnableConfig,
) -> dict:
    text = _models(runtime).answer_unavailable(
        message=message,
        history=history_summary(messages),
        config=config,
    )
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


def _models(runtime: Runtime[AgentContext]) -> RouterModels:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    if runtime.context.models is not None:
        return runtime.context.models
    return default_models()
