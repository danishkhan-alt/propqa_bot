"""The process-wide memory backends: the memory cache (Redis, or in-process in tests) and
the long-term memory repository in Postgres."""

from __future__ import annotations

from psycopg.rows import dict_row

from agent.memory.storage.cache import InProcessMemoryCache, RedisMemoryCache
from agent.memory.storage.in_memory_repository import InMemoryMemoryRepository
from agent.memory.storage.langgraph_store import PropQAMemoryStore
from agent.memory.storage.postgres import PostgresMemoryRepository
from common.db import close_pool, get_pool
from config import ENVIRONMENT, ActiveConfig

MemoryCache = InProcessMemoryCache | RedisMemoryCache

_repository: InMemoryMemoryRepository | None = None
_memory_cache: MemoryCache | None = None


def get_repository() -> InMemoryMemoryRepository | None:
    return _repository


def set_repository(repository: InMemoryMemoryRepository | None) -> None:
    global _repository
    _repository = repository


def get_memory_cache() -> MemoryCache | None:
    return _memory_cache


def set_memory_cache(memory_cache: MemoryCache | None) -> None:
    global _memory_cache
    _memory_cache = memory_cache


def connect_memory_cache() -> MemoryCache:
    """Connect the memory cache and register it for the process."""
    if ENVIRONMENT.is_test:
        memory_cache: MemoryCache = InProcessMemoryCache()
    else:
        if not ActiveConfig.REDIS_URL:
            raise RuntimeError("REDIS_URL is required for working memory")
        memory_cache = RedisMemoryCache(ActiveConfig.REDIS_URL)
    set_memory_cache(memory_cache)
    return memory_cache


def open_long_term_store() -> PropQAMemoryStore:
    """Create the pgvector schema and the store the chat graph compiles with."""
    pool = get_pool(
        "memory",
        min_size=ActiveConfig.CHAT_DB_POOL_MIN,
        max_size=ActiveConfig.CHAT_DB_POOL_MAX,
        connect_kwargs={"row_factory": dict_row},
    )
    repository = PostgresMemoryRepository(pool)
    try:
        repository.ensure_schema()
    except Exception as exc:
        close_pool("memory")
        raise RuntimeError(
            "Memory schema needs Postgres with pgvector (CREATE EXTENSION vector)."
        ) from exc
    set_repository(repository)
    return PropQAMemoryStore(repository)


def close_memory_backends() -> None:
    """Close the memory cache and the memory database pool, and forget both."""
    memory_cache = get_memory_cache()
    set_memory_cache(None)
    set_repository(None)
    if memory_cache is not None:
        memory_cache.close()
    close_pool("memory")
