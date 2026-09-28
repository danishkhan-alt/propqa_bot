"""Graph node that ends a turn: record the lookup for follow-ups, save working memory, and
drop the per-turn data the checkpointer should not keep."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from agent.enums.routing import Route
from agent.graph.nodes.runtime import thread_id_for
from agent.memory.models.records import clone_frame
from agent.memory.session.last_search import build_last_search
from agent.memory.session.search_results import summarize_search_results
from agent.memory.session.working_memory import save_working_memory
from agent.schemas.routes import as_assumptions, as_domain_route, as_query_route
from agent.services.transcript import latest_user_text
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.turn_end")


def record_search_and_clear_turn_state(state: ChatState, config: RunnableConfig) -> dict:
    """Drop catalog YAML and grounded ids so the checkpointer does not keep them."""
    update: dict = {
        "catalog_context": "",
        "loaded_domains": [],
        "grounding": None,
        "listing_ids": [],
        "listing_cards": [],
        "focused_listings": [],
        "map_pins": [],
        "awaiting_sql": False,
    }
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    if query is not None and query.route is Route.NEED_DB and domain is not None and domain.domain_ids:
        update["last_need_db"] = build_last_search(
            message=latest_user_text(state.get("messages") or []),
            query=query,
            domain=domain,
            assumptions=as_assumptions(state.get("assumptions")),
            rows=list(state.get("sql_rows") or []),
            sql_result=state.get("sql_result") or {},
            listing_ids=[str(item) for item in (state.get("listing_ids") or []) if str(item).strip()],
        )
        update["sql_result"] = None
        logger.info(
            "catalog.unload",
            extra={"extra_data": {"domain_ids": domain.domain_ids, "join_ids": domain.join_ids}},
        )
    update.update(_save_working_memory({**state, **update}, config))
    return update


def _save_working_memory(state: ChatState, config: RunnableConfig | None) -> dict:
    """Summarize the result rows into the search frame, then save the frame for this chat."""
    update: dict[str, Any] = {}
    frame = clone_frame(state.get("query_frame")) if state.get("query_frame") else None
    rows = state.get("sql_rows")
    if rows:
        if frame is None:
            frame = clone_frame(None)
        frame["result_meta"] = summarize_search_results(list(rows))
        update["query_frame"] = frame
        update["sql_rows"] = []
    thread_id = thread_id_for(config)
    if thread_id:
        save_working_memory(
            thread_id,
            update.get("query_frame", state.get("query_frame")),
            state.get("goal"),
            bool(state.get("ignore_defaults")),
        )
    return update
