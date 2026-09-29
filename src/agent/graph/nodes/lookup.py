"""Graph nodes: ground the names in the message, then answer the lookup from the warehouse.

A property search is written in code from the router's filters. Any other lookup is drafted
by the model from the loaded catalog. A listing result is ids; they are filled into cards
here, once, for the UI and the answer.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.grounding import get_grounding_cache, ground_features, ground_names
from agent.schemas.grounding import GroundedFeature, GroundedName, Grounding
from agent.schemas.routes import as_domain_route, as_query_route
from agent.services.llm.models import get_default_models
from agent.services.stream_events import publish_stream_event
from agent.services.tracing import get_langfuse_client
from agent.sql.cards import fetch_listing_card_rows, fetch_listing_cards
from agent.sql.execute import run_against_warehouse
from agent.sql.guard import tables_in_domains
from agent.sql.listing_sql_fragments import LISTINGS_TABLE
from agent.sql.lookup import run_listing_lookup, run_sql_lookup, uses_listing_search
from agent.sql.transit import fetch_nearest_station_rows, nearest_station_pins
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.grounding")

# How long a turn waits for the first grounding index after the app starts. A later
# refresh never blocks: the previous copy keeps serving.
FIRST_LOAD_WAIT_SECONDS = 30.0


def resolve_mentioned_names(state: ChatState, runtime: Runtime[AgentContext]) -> dict:
    """Match each name the router found to places and stored values in the loaded tables, and
    each listing requirement to the amenities and views listings are tagged with."""
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    listing_search = uses_listing_search(state)
    requirements = list(query.listing_filters.requirements) if listing_search and query is not None else []
    if query is None or domain is None or not (query.names or requirements):
        return {"grounding": None}
    index = runtime.context.grounding if runtime.context is not None else None
    if index is None:
        index = get_grounding_cache().wait_for_first_load(FIRST_LOAD_WAIT_SECONDS)
    if index is None:
        # Never drop a name: unmatched names are still searched as text, and unmatched
        # requirements are reported as not checked.
        logger.info(
            "grounding.not_ready",
            extra={"extra_data": {"names": [name.text for name in query.names], "requirements": requirements}},
        )
        unmatched = [
            GroundedName(text=name.text, kind=name.kind) for name in query.names
        ]
        return {
            "grounding": Grounding(
                names=unmatched, features=[GroundedFeature(text=text) for text in requirements]
            )
        }
    tables = tables_in_domains([*domain.domain_ids, *domain.join_ids])
    if listing_search:
        tables.add(LISTINGS_TABLE)
    grounding = ground_names(query.names, index, tables)
    grounding.features = ground_features(requirements, index.features)
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
                "features": {feature.text: feature.titles for feature in grounding.features},
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
        kinds = list((update.get("sql_result") or {}).get("station_kinds") or [])
        if kinds:
            update["map_pins"] = _station_map_pins(runtime, ids, cards, kinds)
    return update


def _station_map_pins(
    runtime: Runtime[AgentContext], ids: list, cards: list[dict], kinds: list[str]
) -> list[dict]:
    """A search near stations pins each listing and the station it is near."""
    loader = runtime.context.nearest_station_loader or fetch_nearest_station_rows
    try:
        rows = loader([int(item) for item in ids if str(item).isdigit()], kinds)
    except Exception:
        logger.warning("transit.nearest_station failed", exc_info=True)
        return []
    return nearest_station_pins(cards, list(rows or []))
