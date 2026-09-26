"""The process-wide checkpoint saver the chat graph compiles with.

Each turn writes a checkpoint in Redis and expires after a day. Long-term memory
lives in Postgres, not in the checkpoint. Tests use an in-memory saver.
"""

from __future__ import annotations

import threading

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from agent.checkpointer.redis_checkpoint import RedisCheckpoint
from common.db import close_pool
from common.logger import get_logger

logger = get_logger("agent.checkpointer")

# RedisSaver stores TTL in minutes. A day is the short-term checkpoint window.
_CHECKPOINT_TTL_MINUTES = 60 * 24

_saver: BaseCheckpointSaver | None = None
_lock = threading.Lock()


def get_checkpointer() -> BaseCheckpointSaver:
    """The saver `get_chat_graph` compiles with. Redis outside tests."""
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
    """Drop the saver. The next `get_checkpointer` opens a new one."""
    global _saver
    with _lock:
        saver = _saver
        _saver = None
        _drop_compiled_graph()
    _close_saver(saver)
    close_pool("checkpointer")
    from agent.memory.session.bootstrap import close_memory

    close_memory()


def _drop_compiled_graph() -> None:
    from agent.graphs import workflow

    workflow._graph = None


def _open_saver() -> BaseCheckpointSaver:
    from config import ENVIRONMENT, ActiveConfig

    if ENVIRONMENT.is_test:
        return InMemorySaver()
    if not ActiveConfig.REDIS_URL:
        raise RuntimeError("REDIS_URL is required for chat checkpoints")

    saver = RedisCheckpoint(
        redis_url=ActiveConfig.REDIS_URL,
        ttl={"default_ttl": _CHECKPOINT_TTL_MINUTES, "refresh_on_read": True},
    )
    saver.setup()
    logger.info("Chat checkpointer ready")
    return saver


def _close_saver(saver: BaseCheckpointSaver | None) -> None:
    if saver is None:
        return
    client = getattr(saver, "_redis", None)
    if client is not None and getattr(saver, "_owns_its_client", False):
        client.close()
