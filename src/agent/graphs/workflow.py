from __future__ import annotations

import functools
import time

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.checkpointer import get_checkpointer
from agent.context import AgentContext
from agent.graphs.answer import write_reply
from agent.graphs.catalog import load_domain_catalog, record_search_and_clear_turn_state
from agent.graphs.focus import load_focused_listings, next_step_after_session_context
from agent.graphs.memory import (
    personalize_search_frame,
    ask_before_forgetting_memory,
    queue_memory_extraction,
    recall_long_term_memories,
    update_search_frame,
    next_step_after_search_frame_update,
)
from agent.graphs.router import (
    choose_data_domains,
    load_session_context,
    choose_query_route,
    next_step_after_domain_choice,
    next_step_after_query_route,
)
from agent.graphs.sql import resolve_mentioned_names, run_warehouse_lookup
from agent.states.chat import ChatInput, ChatState
from common.logger import get_logger

logger = get_logger("agent.workflow")

_graph: CompiledStateGraph | None = None


def build_chat_graph(checkpointer=None, store=None) -> CompiledStateGraph:
    """Choose the query route, then the data domains, load their catalog, resolve the names
    the message mentions, and run a read-only warehouse lookup.

    Memory runs around that path: load the session context, recall long-term memories,
    update the search frame, then queue memory extraction after the reply.

    A turn about listings the user picked on screen skips routing and lookup: it loads
    those listings' adverts and replies from them.
    """
    builder = StateGraph(ChatState, context_schema=AgentContext, input_schema=ChatInput)
    for node in (
        load_session_context,
        load_focused_listings,
        recall_long_term_memories,
        update_search_frame,
        ask_before_forgetting_memory,
        choose_query_route,
        choose_data_domains,
        personalize_search_frame,
        load_domain_catalog,
        resolve_mentioned_names,
        run_warehouse_lookup,
        write_reply,
        queue_memory_extraction,
        record_search_and_clear_turn_state,
    ):
        builder.add_node(node.__name__, with_node_timing(node))

    builder.add_edge(START, "load_session_context")
    builder.add_conditional_edges("load_session_context", next_step_after_session_context, ["load_focused_listings", "recall_long_term_memories"])
    builder.add_edge("load_focused_listings", "write_reply")
    builder.add_edge("recall_long_term_memories", "update_search_frame")
    builder.add_conditional_edges("update_search_frame", next_step_after_search_frame_update, ["ask_before_forgetting_memory", "choose_query_route"])
    builder.add_edge("ask_before_forgetting_memory", END)
    builder.add_conditional_edges("choose_query_route", next_step_after_query_route, ["choose_data_domains", "write_reply"])
    builder.add_conditional_edges("choose_data_domains", next_step_after_domain_choice, ["personalize_search_frame", "write_reply"])
    builder.add_edge("personalize_search_frame", "load_domain_catalog")
    builder.add_edge("load_domain_catalog", "resolve_mentioned_names")
    builder.add_edge("resolve_mentioned_names", "run_warehouse_lookup")
    builder.add_edge("run_warehouse_lookup", "write_reply")
    builder.add_edge("write_reply", "queue_memory_extraction")
    builder.add_edge("queue_memory_extraction", "record_search_and_clear_turn_state")
    builder.add_edge("record_search_and_clear_turn_state", END)
    return builder.compile(checkpointer=checkpointer, store=store)


def with_node_timing(node):
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
            logger.info("node.timing", extra={"extra_data": {"node": node.__name__, "ms": elapsed_ms}})

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
