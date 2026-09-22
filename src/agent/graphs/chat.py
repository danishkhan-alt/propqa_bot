from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.context import AgentContext, RouterModels
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


def build_chat_graph(checkpointer=None) -> CompiledStateGraph:
    """Query router, then domain router and catalog load when the turn needs the warehouse.

    The SQL agent is not in this graph yet. A need_db turn loads the catalog, then
    finalize drops the YAML and leaves awaiting_sql set.
    """
    builder = StateGraph(ChatState, context_schema=AgentContext, input_schema=ChatInput)
    builder.add_node("load_context", load_context)
    builder.add_node("query_router", query_router)
    builder.add_node("domain_router", domain_router)
    builder.add_node("catalog_load", catalog_load)
    builder.add_node("answer", answer)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "query_router")
    builder.add_conditional_edges("query_router", route_after_query, ["domain_router", "answer"])
    builder.add_conditional_edges("domain_router", route_after_domain, ["catalog_load", "answer"])
    builder.add_edge("catalog_load", "answer")
    builder.add_edge("answer", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


def get_chat_graph() -> CompiledStateGraph:
    global _graph
    if _graph is None:
        _graph = build_chat_graph(InMemorySaver())
    return _graph


def run_turn(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    models: RouterModels | None = None,
) -> dict:
    """Run one user turn. `thread_id` keeps last_need_db for follow-ups."""
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
