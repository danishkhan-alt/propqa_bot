"""Thread persistence for the chat graph.

Each turn writes a checkpoint. The next turn updates that thread. `delete_thread`
removes it. The router nodes are unchanged; only the saver behind the graph differs.
"""

from __future__ import annotations

import threading

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

from common.db import close_pool, get_pool
from common.logger import get_logger

logger = get_logger("agent.checkpointer")

# LangGraph's saver opens its own transactions and reads dict rows.
_CHECKPOINTER_CONNECT = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}

_saver: BaseCheckpointSaver | None = None
_lock = threading.Lock()


def get_checkpointer() -> BaseCheckpointSaver:
    """The saver `get_chat_graph` compiles with. Postgres, except in tests."""
    global _saver
    if _saver is not None:
        return _saver
    with _lock:
        if _saver is None:
            _saver = _open_saver()
        return _saver


def delete_thread(thread_id: str) -> None:
    """Delete every checkpoint for one chat. Other threads stay."""
    if not str(thread_id).strip():
        raise ValueError("thread_id is required")
    get_checkpointer().delete_thread(str(thread_id))


def close_checkpointer() -> None:
    """Drop the saver and its pool. The next `get_checkpointer` opens a new one."""
    global _saver
    with _lock:
        _saver = None
        _drop_compiled_graph()
    close_pool("checkpointer")


def _drop_compiled_graph() -> None:
    from agent.graphs import chat as chat_graph

    chat_graph._graph = None


def _open_saver() -> BaseCheckpointSaver:
    from config import ENVIRONMENT, ActiveConfig

    if ENVIRONMENT.is_test:
        return InMemorySaver()

    pool = get_pool(
        "checkpointer",
        min_size=ActiveConfig.CHAT_DB_POOL_MIN,
        max_size=ActiveConfig.CHAT_DB_POOL_MAX,
        connect_kwargs=_CHECKPOINTER_CONNECT,
    )
    saver = PostgresSaver(pool)
    saver.setup()
    logger.info("Chat checkpointer ready")
    return saver
