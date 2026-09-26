"""Graph nodes: ground the names in the message, then answer the lookup from the warehouse.

A property search is written in code from the router's filters. Any other lookup is drafted
by the model from the loaded catalog. A listing result is ids; they are filled into cards
here, once, for the UI and the answer.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.grounding import get_grounding_cache, ground_names
from agent.schemas.grounding import GroundedName, Grounding
from agent.schemas.routes import as_domain_route, as_query_route
from agent.services.llm.models import get_default_models
from agent.services.stream_events import publish_stream_event
from agent.services.tracing import get_langfuse_client
from agent.sql.cards import fetch_listing_card_rows, fetch_listing_cards
from agent.sql.execute import run_against_warehouse
from agent.sql.guard import tables_in_domains
from agent.sql.listing_sql_fragments import LISTINGS_TABLE
from agent.sql.lookup import run_listing_lookup, run_sql_lookup, uses_listing_search
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.grounding")


def resolve_mentioned_names(state: ChatState, runtime: Runtime[AgentContext]) -> dict:
    """Match each name the router found to places and stored values in the loaded tables."""
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    if query is None or domain is None or not query.names:
        return {"grounding": None}
    index = runtime.context.grounding if runtime.context is not None else None
    if index is None:
        index = get_grounding_cache().get()
    if index is None:
        # Never drop a name: unmatched names are still searched as text, and the reply says so.
        logger.info(
            "grounding.not_ready",
            extra={"extra_data": {"names": [name.text for name in query.names]}},
        )
        unmatched = [
            GroundedName(text=name.text, kind=name.kind) for name in query.names
        ]
        return {"grounding": Grounding(names=unmatched)}
    tables = tables_in_domains([*domain.domain_ids, *domain.join_ids])
    if uses_listing_search(state):
        tables.add(LISTINGS_TABLE)
    grounding = ground_names(query.names, index, tables)
    logger.info(
        "grounding.names",
        extra={
            "extra_data": {
                "names": [
                    {
                        "text": name.text,
                        "place": name.place.title if name.place else None,
                        "stored": len(name.stored),
                    }
                    for name in grounding.names
                ],
                "unresolved": grounding.unresolved_names(),
            }
        },
    )
    return {"grounding": grounding}


def run_warehouse_lookup(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    runner = runtime.context.sql_runner or run_against_warehouse
    if uses_listing_search(state):
        update = run_listing_lookup(state, runner, client=get_langfuse_client())
    else:
        models = (
            runtime.context.models
            if runtime.context.models is not None
            else get_default_models()
        )
        update = run_sql_lookup(
            state,
            models,
            runner,
            config=config,
            client=get_langfuse_client(),
        )
    ids = list(update.get("listing_ids") or [])
    if ids:
        loader = runtime.context.listing_loader or fetch_listing_card_rows
        cards = fetch_listing_cards(ids, loader)
        update["listing_cards"] = cards
        publish_stream_event("listings", ids=ids, cards=cards)
    return update
