"""Graph node: catalog is loaded, so draft SQL, run it, and keep the rows for the answer.

A listing result is ids. Those ids are filled into cards here, once, for the UI and the answer.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext
from agent.services.llm import default_models
from agent.services.tracing import langfuse_client
from agent.services.events import publish
from agent.sql.cards import listing_cards, load_from_warehouse
from agent.sql.execute import run_against_warehouse
from agent.sql.lookup import run_sql_lookup
from agent.states.chat import ChatState


def sql_lookup(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    models = runtime.context.models if runtime.context.models is not None else default_models()
    runner = runtime.context.sql_runner or run_against_warehouse
    update = run_sql_lookup(
        state,
        models,
        runner,
        config=config,
        client=langfuse_client(),
    )
    ids = list(update.get("listing_ids") or [])
    if ids:
        loader = runtime.context.listing_loader or load_from_warehouse
        cards = listing_cards(ids, loader)
        update["listing_cards"] = cards
        publish("listings", ids=ids, cards=cards)
    return update
