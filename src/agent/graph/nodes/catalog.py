"""Graph nodes that load the catalog for a lookup and clear it when the turn ends."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from agent.enums.routing import Route
from agent.graphs.memory import save_working_memory
from agent.memory.session.search_results import summarize_search_results
from agent.schemas.routes import (
    LastNeedDb,
    as_assumptions,
    as_domain_route,
    as_query_route,
)
from agent.services.catalog_index import render_catalog, table_count
from agent.services.transcript import latest_user_text
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.router")


def load_domain_catalog(state: ChatState) -> dict:
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


def record_search_and_clear_turn_state(state: ChatState, config: RunnableConfig) -> dict:
    """Drop catalog YAML and grounded ids so the checkpointer does not keep them."""
    update: dict = {
        "catalog_context": "",
        "loaded_domains": [],
        "grounding": None,
        "listing_ids": [],
        "listing_cards": [],
        "focused_listings": [],
    }
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
        listing_ids = [
            str(item) for item in (state.get("listing_ids") or []) if str(item).strip()
        ]
        if listing_ids:
            meta["ids"] = listing_ids
        # A refine starts from these, so "cheaper" keeps the place and the filters.
        if query.names:
            meta["names"] = [name.model_dump(mode="json") for name in query.names]
        if query.listing_filters is not None:
            meta["listing_filters"] = query.listing_filters.model_dump(
                mode="json", exclude_defaults=True
            )
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
    update.update(save_working_memory({**state, **update}, config))
    return update
