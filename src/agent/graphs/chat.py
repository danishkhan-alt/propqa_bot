from __future__ import annotations

from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from agent.checkpointer import get_checkpointer
from agent.context import AgentContext, RouterModels
from agent.graphs.memory import (
    apply_defaults,
    confirm_forget,
    enqueue_extraction,
    recall_memory,
    refine_or_new,
    route_after_refine,
)
from agent.graphs.nodes import (
    answer,
    catalog_load,
    domain_router,
    finalize,
    load_context,
    query_router,
    route_after_domain,
    route_after_query,
)
from agent.graphs.sql import sql_lookup
from agent.schemas.routes import as_query_route
from agent.services.tracing import langfuse_client
from agent.states.chat import ChatInput, ChatState
from common.logger import get_logger

logger = get_logger("agent.router")

_graph: CompiledStateGraph | None = None


def build_chat_graph(checkpointer=None, store=None) -> CompiledStateGraph:
    """Query router, then domain router, catalog load, and a read-only SQL lookup.

    Memory runs around that path: load working state, recall long-term items, refine the
    query frame, then queue extraction after the answer.
    """
    builder = StateGraph(ChatState, context_schema=AgentContext, input_schema=ChatInput)
    builder.add_node("load_context", load_context)
    builder.add_node("recall_memory", recall_memory)
    builder.add_node("refine_or_new", refine_or_new)
    builder.add_node("confirm_forget", confirm_forget)
    builder.add_node("query_router", query_router)
    builder.add_node("domain_router", domain_router)
    builder.add_node("apply_defaults", apply_defaults)
    builder.add_node("catalog_load", catalog_load)
    builder.add_node("sql_lookup", sql_lookup)
    builder.add_node("answer", answer)
    builder.add_node("enqueue_extraction", enqueue_extraction)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "recall_memory")
    builder.add_edge("recall_memory", "refine_or_new")
    builder.add_conditional_edges("refine_or_new", route_after_refine, ["confirm_forget", "query_router"])
    builder.add_edge("confirm_forget", END)
    builder.add_conditional_edges("query_router", route_after_query, ["domain_router", "answer"])
    builder.add_conditional_edges("domain_router", route_after_domain, ["apply_defaults", "answer"])
    builder.add_edge("apply_defaults", "catalog_load")
    builder.add_edge("catalog_load", "sql_lookup")
    builder.add_edge("sql_lookup", "answer")
    builder.add_edge("answer", "enqueue_extraction")
    builder.add_edge("enqueue_extraction", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer, store=store)


def get_chat_graph() -> CompiledStateGraph:
    global _graph
    if _graph is None:
        from config import ENVIRONMENT

        store = None
        if not ENVIRONMENT.is_test:
            from agent.memory.session.bootstrap import open_hot, open_long_term_store

            open_hot()
            store = open_long_term_store()
        _graph = build_chat_graph(get_checkpointer(), store=store)
    return _graph


def run_turn(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    models: RouterModels | None = None,
) -> dict:
    """Run one user turn. `thread_id` reloads and updates that chat."""
    client = langfuse_client()
    callbacks = _tracing_callbacks(client)

    def invoke() -> dict:
        result = get_chat_graph().invoke(
            {"messages": [HumanMessage(content=message)]},
            config={
                "configurable": {"thread_id": thread_id, "user_id": user_id},
                "callbacks": callbacks,
                "metadata": {"user_id": user_id, "session_id": thread_id},
            },
            context=AgentContext(user_id=user_id, models=models),
            version="v2",
        )
        value = getattr(result, "value", result)
        return value if isinstance(value, dict) else dict(value)

    if client is None:
        return invoke()
    from langfuse import propagate_attributes

    with propagate_attributes(user_id=user_id, session_id=thread_id):
        result = invoke()
    client.flush()
    return result


async def stream_turn(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    models: RouterModels | None = None,
    sql_runner=None,
    listing_loader=None,
    graph: CompiledStateGraph | None = None,
    session_profile: dict | None = None,
) -> AsyncIterator[dict]:
    """Yield listing cards and text deltas as the turn runs, then a done event."""
    compiled = graph or get_chat_graph()
    client = langfuse_client()
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "callbacks": _tracing_callbacks(client),
        "metadata": {"user_id": user_id, "session_id": thread_id},
    }
    context = AgentContext(
        user_id=user_id, models=models, sql_runner=sql_runner, listing_loader=listing_loader
    )

    async def events() -> AsyncIterator[dict]:
        paused_at_start = await _is_paused(compiled, config)
        graph_input = (
            Command(resume=message)
            if paused_at_start
            else {"messages": [HumanMessage(content=message)]}
        )
        if session_profile is not None and not paused_at_start:
            graph_input["session_profile"] = session_profile
        async for item in compiled.astream(
            graph_input,
            config=config,
            context=context,
            stream_mode=["custom", "updates"],
            version="v2",
        ):
            mode, chunk = _stream_item(item)
            if mode == "custom" and isinstance(chunk, dict) and chunk.get("event"):
                yield chunk
                continue
            if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
                prompt = _interrupt_text(chunk["__interrupt__"])
                if prompt:
                    yield {"event": "text", "delta": prompt}
        final = await compiled.aget_state(config)
        values = getattr(final, "values", None) or {}
        query = as_query_route(values.get("query_route"))
        yield {
            "event": "done",
            "thread_id": thread_id,
            "route": query.route.value if query is not None else None,
            "paused": bool(getattr(final, "interrupts", None)),
        }

    if client is None:
        async for event in events():
            yield event
        return
    from langfuse import propagate_attributes

    with propagate_attributes(user_id=user_id, session_id=thread_id):
        async for event in events():
            yield event
    client.flush()


async def _is_paused(graph: CompiledStateGraph, config: dict) -> bool:
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        return False
    return bool(getattr(snapshot, "interrupts", None))


def _stream_item(item) -> tuple:
    """LangGraph v2 yields `{type, data}`. Older runs yield `(mode, data)`."""
    if isinstance(item, dict) and "type" in item and "data" in item:
        return item["type"], item["data"]
    if isinstance(item, tuple) and len(item) == 3 and isinstance(item[1], str):
        return item[1], item[2]
    if isinstance(item, tuple) and len(item) == 2:
        return item[0], item[1]
    return None, None


def _interrupt_text(raw) -> str:
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    for item in items:
        value = getattr(item, "value", item)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            prompt = value.get("prompt") or value.get("message")
            if prompt:
                return str(prompt).strip()
    return ""


def _tracing_callbacks(client) -> list:
    if client is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("langfuse is not installed; router traces stay in app logs")
        return []
    return [CallbackHandler()]
