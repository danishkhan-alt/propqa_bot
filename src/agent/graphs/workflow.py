from __future__ import annotations

import functools
import time

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.checkpointer import get_checkpointer
from agent.context import AgentContext
from agent.graphs.answer import answer
from agent.graphs.catalog import catalog_load, finalize
from agent.graphs.focus import listing_focus, route_after_load
from agent.graphs.memory import (
    apply_defaults,
    confirm_forget,
    enqueue_extraction,
    recall_memory,
    refine_or_new,
    route_after_refine,
)
from agent.graphs.router import (
    domain_router,
    load_context,
    query_router,
    route_after_domain,
    route_after_query,
)
from agent.graphs.sql import ground_message_names, sql_lookup
from agent.states.chat import ChatInput, ChatState
from common.logger import get_logger

logger = get_logger("agent.workflow")

_graph: CompiledStateGraph | None = None


def build_chat_graph(checkpointer=None, store=None) -> CompiledStateGraph:
    """Query router, then domain router, catalog load, name grounding, and a read-only SQL lookup.

    Memory runs around that path: load working state, recall long-term items, refine the
    query frame, then queue extraction after the answer.

    A turn about listings the user picked on screen skips routing and lookup: it loads
    those listings' adverts and answers from them.
    """
    builder = StateGraph(ChatState, context_schema=AgentContext, input_schema=ChatInput)
    builder.add_node("load_context", timed("load_context", load_context))
    builder.add_node("listing_focus", timed("listing_focus", listing_focus))
    builder.add_node("recall_memory", timed("recall_memory", recall_memory))
    builder.add_node("refine_or_new", timed("refine_or_new", refine_or_new))
    builder.add_node("confirm_forget", timed("confirm_forget", confirm_forget))
    builder.add_node("query_router", timed("query_router", query_router))
    builder.add_node("domain_router", timed("domain_router", domain_router))
    builder.add_node("apply_defaults", timed("apply_defaults", apply_defaults))
    builder.add_node("catalog_load", timed("catalog_load", catalog_load))
    builder.add_node("ground_names", timed("ground_names", ground_message_names))
    builder.add_node("sql_lookup", timed("sql_lookup", sql_lookup))
    builder.add_node("answer", timed("answer", answer))
    builder.add_node("enqueue_extraction", timed("enqueue_extraction", enqueue_extraction))
    builder.add_node("finalize", timed("finalize", finalize))

    builder.add_edge(START, "load_context")
    builder.add_conditional_edges("load_context", route_after_load, ["listing_focus", "recall_memory"])
    builder.add_edge("listing_focus", "answer")
    builder.add_edge("recall_memory", "refine_or_new")
    builder.add_conditional_edges("refine_or_new", route_after_refine, ["confirm_forget", "query_router"])
    builder.add_edge("confirm_forget", END)
    builder.add_conditional_edges("query_router", route_after_query, ["domain_router", "answer"])
    builder.add_conditional_edges("domain_router", route_after_domain, ["apply_defaults", "answer"])
    builder.add_edge("apply_defaults", "catalog_load")
    builder.add_edge("catalog_load", "ground_names")
    builder.add_edge("ground_names", "sql_lookup")
    builder.add_edge("sql_lookup", "answer")
    builder.add_edge("answer", "enqueue_extraction")
    builder.add_edge("enqueue_extraction", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer, store=store)


def timed(name: str, node):
    """Log how long a graph node took, so a slow turn shows which step it spent its time in.

    functools.wraps keeps the node's signature visible, so LangGraph still injects
    config and runtime by parameter name.
    """

    @functools.wraps(node)
    def run(*args, **kwargs):
        started = time.perf_counter()
        try:
            return node(*args, **kwargs)
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info("node.timing", extra={"extra_data": {"node": name, "ms": elapsed_ms}})

    return run


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
