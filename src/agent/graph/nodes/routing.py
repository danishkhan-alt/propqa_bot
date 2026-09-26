"""Graph nodes that choose the route and the data domains for a turn, and the branches after them."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.enums.routing import Route, TurnKind
from agent.graph.nodes.runtime import models_for
from agent.reply.buyer_profile import merge_profile
from agent.schemas.routes import (
    DomainRoute,
    as_domain_route,
    as_last_need_db,
    as_query_route,
)
from agent.services.catalog_prompt_text import render_domain_blurbs, render_domain_index
from agent.services.transcript import format_recent_history, latest_user_text
from agent.sql.listing_search import property_type_names
from agent.sql.recipes import recipe_index_text
from agent.states.chat import ChatState
from agent.validator import build_lookup_assumptions, sanitize_domain_route, sanitize_query_route
from common.logger import get_logger

logger = get_logger("agent.routing")


def choose_query_route(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    messages = state.get("messages") or []
    message = latest_user_text(messages)
    last = as_last_need_db(state.get("last_need_db"))
    route = models_for(runtime).route_query(
        message=message,
        history=format_recent_history(messages),
        last_need_db=last,
        domain_blurbs=render_domain_blurbs(),
        memory_context=state.get("memory_block") or "",
        property_types=property_type_names(),
        config=config,
    )
    route, notes = sanitize_query_route(route, last)

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
        assumptions = build_lookup_assumptions(route)
    update: dict = {
        "query_route": route,
        "assumptions": assumptions,
        "session_profile": merge_profile(state.get("session_profile"), route.profile),
    }
    if route.route is not Route.NEED_DB:
        update["domain_route"] = None
        update["awaiting_sql"] = False
    return update


def choose_data_domains(
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
            index_text=render_domain_index(),
            recipes_text=recipe_index_text(),
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
                "recipe_id": route.recipe_id,
                "confidence": route.confidence,
                "rationale": route.rationale,
                "notes": notes,
                "user_id": runtime.context.user_id,
            }
        },
    )
    return {"query_route": query, "domain_route": route}


def next_step_after_query_route(state: ChatState) -> str:
    query = as_query_route(state.get("query_route"))
    if query is not None and query.route is Route.NEED_DB:
        return "choose_data_domains"
    return "write_reply"


def next_step_after_domain_choice(state: ChatState) -> str:
    domain = as_domain_route(state.get("domain_route"))
    if domain is not None and domain.domain_ids:
        return "personalize_search_frame"
    return "write_reply"
