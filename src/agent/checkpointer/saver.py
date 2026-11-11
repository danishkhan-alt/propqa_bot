"""The process-wide checkpoint saver the chat graph compiles with.

Each turn writes a LangGraph checkpoint in the chatbot database, schema ai_chatbot.
Tests use an in-memory saver.
"""

from __future__ import annotations

import os
import threading

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from psycopg.rows import dict_row

from agent.checkpointer.postgres_checkpoint_saver import PostgresCheckpointSaver
from common.db import chat_schema_connect_kwargs, close_pool, get_pool
from common.logger import get_logger
from config import ENVIRONMENT, ActiveConfig

logger = get_logger("agent.checkpointer")

POOL_NAME = "checkpointer"

_saver: BaseCheckpointSaver | None = None
_lock = threading.Lock()


def get_checkpointer() -> BaseCheckpointSaver:
    """The saver `get_chat_graph` compiles with. Postgres outside tests."""
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
    """Drop the saver. The next `get_checkpointer` opens a new one, and the chat graph
    recompiles with it."""
    global _saver
    with _lock:
        saver = _saver
        _saver = None
    _close_saver(saver)
    close_pool(POOL_NAME)


def _open_saver() -> BaseCheckpointSaver:
    if ENVIRONMENT.is_test or os.environ.get("PYTEST_CURRENT_TEST"):
        return InMemorySaver()
    pool = get_pool(
        POOL_NAME,
        min_size=ActiveConfig.CHAT_DB_POOL_MIN,
        max_size=ActiveConfig.CHAT_DB_POOL_MAX,
        connect_kwargs=chat_schema_connect_kwargs(
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        ),
    )
    try:
        saver = PostgresCheckpointSaver(pool)
        saver.setup()
        from common.session.chat_migration import migrate_redis_chats

        migrate_redis_chats(pool, saver)
    except Exception:
        close_pool(POOL_NAME)
        raise
    logger.info("Chat checkpointer ready")
    return saver


def _close_saver(saver: BaseCheckpointSaver | None) -> None:
    if saver is None:
        return
    client = getattr(saver, "_redis", None)
    if client is not None and getattr(saver, "_owns_its_client", False):
        client.close()
