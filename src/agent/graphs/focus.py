"""Graph node for a turn about listings the user picked on screen.

The ids arrive with the message, so there is nothing to route, ground, or draft: the node
loads each listing's full advert with one fixed statement, and the answer reads it.
"""

from __future__ import annotations

from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.sql.cards import load_from_warehouse
from agent.sql.listing_details import focused_listing_facts, load_details_from_warehouse
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.router")


def listing_focus(state: ChatState, runtime: Runtime[AgentContext]) -> dict:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    ids = list(state.get("focused_property_ids") or [])
    listings = focused_listing_facts(
        ids,
        runtime.context.listing_loader or load_from_warehouse,
        runtime.context.listing_detail_loader or load_details_from_warehouse,
    )
    logger.info(
        "listing.focus",
        extra={"extra_data": {"ids": ids, "found": len(listings), "user_id": runtime.context.user_id}},
    )
    # No lookup runs this turn. Clearing the route keeps finalize from recording the
    # previous search again, so a later "cheaper" still refines that search.
    return {"focused_listings": listings, "query_route": None}


def route_after_load(state: ChatState) -> str:
    return "listing_focus" if state.get("focused_property_ids") else "recall_memory"
