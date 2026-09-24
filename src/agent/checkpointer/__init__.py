"""Thread persistence for the chat graph.

Each turn writes a checkpoint in Redis and expires after a day. Long-term memory
lives in Postgres, not in the checkpoint. The chat API reads those checkpoints
asynchronously, so the saver runs the same Redis calls from a worker thread.
Tests use an in-memory saver.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.redis import RedisSaver

from common.db import close_pool
from common.logger import get_logger

logger = get_logger("agent.checkpointer")

# RedisSaver stores TTL in minutes. A day is the short-term checkpoint window.
_CHECKPOINT_TTL_MINUTES = 60 * 24

_saver: BaseCheckpointSaver | None = None
_lock = threading.Lock()


class RedisCheckpoint(RedisSaver):
    """Redis checkpoints the async chat stream can read and write."""

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        rows = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for row in rows:
            yield row

    async def adelete_thread(self, thread_id: str) -> None:
        await asyncio.to_thread(self.delete_thread, thread_id)


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
    from agent.graphs import chat as chat_graph

    chat_graph._graph = None


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
