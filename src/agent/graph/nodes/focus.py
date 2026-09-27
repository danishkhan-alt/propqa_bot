"""Graph node for a turn about listings the user picked on screen.

The ids arrive with the message, so there is nothing to route, ground, or draft: the node
loads each listing's full advert with one fixed statement, and the answer reads it.
"""

from __future__ import annotations

from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.sql.cards import fetch_listing_card_rows
from agent.sql.listing_details import fetch_focused_listings, fetch_listing_detail_rows
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.focus")


def load_focused_listings(state: ChatState, runtime: Runtime[AgentContext]) -> dict:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    ids = list(state.get("focused_property_ids") or [])
    focused = fetch_focused_listings(
        ids,
        runtime.context.listing_loader or fetch_listing_card_rows,
        runtime.context.listing_detail_loader or fetch_listing_detail_rows,
    )
    logger.info(
        "listing.focus",
        extra={
            "extra_data": {
                "ids": ids,
                "found": len(focused.facts),
                "map_pins": len(focused.map_pins),
                "user_id": runtime.context.user_id,
            }
        },
    )
    # No lookup runs this turn. Clearing the route keeps record_search_and_clear_turn_state from recording the
    # previous search again, so a later "cheaper" still refines that search.
    return {
        "focused_listings": focused.facts,
        "focused_map_pins": focused.map_pins,
        "query_route": None,
    }


def next_step_after_session_context(state: ChatState) -> str:
    return (
        "load_focused_listings"
        if state.get("focused_property_ids")
        else "recall_long_term_memories"
    )
