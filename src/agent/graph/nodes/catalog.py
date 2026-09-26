"""Graph node that loads the table catalog for the chosen data domains."""

from __future__ import annotations

from agent.schemas.routes import as_domain_route
from agent.services.catalog_prompt_text import count_domain_tables, render_catalog
from agent.states.chat import ChatState
from common.logger import get_logger

logger = get_logger("agent.catalog")


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
                "table_count": count_domain_tables(loaded),
            }
        },
    )
    return {"catalog_context": context, "loaded_domains": loaded}
