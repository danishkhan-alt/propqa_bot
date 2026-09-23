from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

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
from agent.states.chat import ChatInput, ChatState
from common.logger import get_logger
from config import ActiveConfig

logger = get_logger("agent.router")

_graph: CompiledStateGraph | None = None


def build_chat_graph(checkpointer=None, store=None) -> CompiledStateGraph:
    """Query router, then domain router and catalog load when the turn needs the warehouse.

    Memory runs around that path: load working state, recall long-term items, refine the
    query frame, then queue extraction after the answer. The SQL agent is not in this
    graph yet.
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
    builder.add_edge("catalog_load", "answer")
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
    result = get_chat_graph().invoke(
        {"messages": [HumanMessage(content=message)]},
        config={
            "configurable": {"thread_id": thread_id, "user_id": user_id},
            "callbacks": _tracing_callbacks(),
            "metadata": {"user_id": user_id, "session_id": thread_id},
        },
        context=AgentContext(user_id=user_id, models=models),
        version="v2",
    )
    value = getattr(result, "value", result)
    return value if isinstance(value, dict) else dict(value)


def _tracing_callbacks() -> list:
    if not ActiveConfig.LANGFUSE_PUBLIC_KEY or not ActiveConfig.LANGFUSE_SECRET_KEY:
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("langfuse is not installed; router traces stay in app logs")
        return []
    return [CallbackHandler()]
