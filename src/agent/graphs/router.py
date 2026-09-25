"""Graph nodes that pick the route and the data domains for a turn."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.enums.routing import Intent, Route, TurnKind
from agent.graphs.memory import read_context
from agent.graphs.runtime import models_for
from agent.reply.clarify import merge_profile
from agent.schemas.routes import (
    Assumptions,
    DomainRoute,
    QueryRoute,
    as_domain_route,
    as_last_need_db,
    as_query_route,
)
from agent.services.catalog_index import domain_blurbs, domain_index_text
from agent.services.transcript import history_summary, latest_user_text
from agent.sql.listing_search import category_names
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
    route = models_for(runtime).route_query(
        message=message,
        history=history_summary(messages),
        last_need_db=last,
        domain_blurbs=domain_blurbs(),
        memory_context=state.get("memory_block") or "",
        property_types=category_names(),
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
        route = models_for(runtime).route_domain(
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
