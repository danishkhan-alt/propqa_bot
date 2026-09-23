"""Process-wide memory repository and Redis hot tier."""

from __future__ import annotations

from psycopg.rows import dict_row

from agent.memory.storage.postgres import PostgresMemoryRepository
from agent.memory.storage.langgraph_store import PropQAMemoryStore
from common.db import close_pool, get_pool
from config import ActiveConfig

from agent.memory.storage.cache import WorkingMemoryCache, RedisMemoryCache
from agent.memory.storage.repository import InMemoryRepository

_repository: InMemoryRepository | None = None
_hot: WorkingMemoryCache | RedisMemoryCache | None = None


def get_repository() -> InMemoryRepository | None:
    return _repository


def set_repository(repository: InMemoryRepository | None) -> None:
    global _repository
    _repository = repository


def get_hot() -> WorkingMemoryCache | RedisMemoryCache | None:
    return _hot


def set_hot(hot: WorkingMemoryCache | RedisMemoryCache | None) -> None:
    global _hot
    _hot = hot


def invalidate(user_id: str) -> None:
    hot = _hot
    if hot is None or not user_id:
        return
    hot.delete(f"profile:{user_id}")
    hot.delete_prefix(f"recall:{user_id}:")


def open_hot() -> WorkingMemoryCache | RedisMemoryCache:
    from config import ENVIRONMENT, ActiveConfig

    if ENVIRONMENT.is_test:
        hot: WorkingMemoryCache | RedisMemoryCache = WorkingMemoryCache()
    else:
        if not ActiveConfig.REDIS_URL:
            raise RuntimeError("REDIS_URL is required for working memory")
        hot = RedisMemoryCache(ActiveConfig.REDIS_URL)
    set_hot(hot)
    return hot


def open_long_term_store():
    """Create the pgvector schema and the store the chat graph compiles with."""

    pool = get_pool(
        "memory",
        min_size=ActiveConfig.CHAT_DB_POOL_MIN,
        max_size=ActiveConfig.CHAT_DB_POOL_MAX,
        connect_kwargs={"row_factory": dict_row},
    )
    repository = PostgresMemoryRepository(pool)
    try:
        repository.setup()
    except Exception as exc:
        close_pool("memory")
        raise RuntimeError(
            "Memory schema needs Postgres with pgvector (CREATE EXTENSION vector)."
        ) from exc
    set_repository(repository)
    return PropQAMemoryStore(repository)


def close_memory() -> None:
    from common.db import close_pool

    hot = get_hot()
    set_hot(None)
    set_repository(None)
    if hot is not None:
        hot.close()
    close_pool("memory")


def load_working(thread_id: str) -> dict | None:
    hot = get_hot()
    if hot is None or not thread_id:
        return None
    value = hot.get(f"wm:{thread_id}")
    return value if isinstance(value, dict) else None


def save_working(thread_id: str, frame, goal, ignore_defaults: bool) -> None:
    hot = get_hot()
    if hot is None or not thread_id:
        return
    from agent.memory.storage.cache import WM_TTL_SECONDS
    from agent.memory.models.types import clone_frame

    stored = clone_frame(frame) if frame else None
    if stored is not None:
        stored["sql"] = (frame or {}).get("sql") or ""
    hot.set(
        f"wm:{thread_id}",
        {"query_frame": stored, "goal": goal, "ignore_defaults": bool(ignore_defaults)},
        ttl=WM_TTL_SECONDS,
    )


def load_profile(user_id: str) -> dict:
    if not user_id:
        return {}
    hot = get_hot()
    if hot is not None:
        cached = hot.get(f"profile:{user_id}")
        if isinstance(cached, dict):
            return cached
    repository = get_repository()
    if repository is None:
        return {}
    profile = repository.get_profile(user_id) or {}
    if profile and hot is not None:
        from agent.memory.storage.cache import PROFILE_TTL_SECONDS

        stored = {
            "summary": profile.get("summary") or "",
            "structured": profile.get("structured") or {},
            "version": profile.get("version") or 1,
        }
        hot.set(f"profile:{user_id}", stored, ttl=PROFILE_TTL_SECONDS)
        return stored
    if not profile:
        return {}
    return {
        "summary": profile.get("summary") or "",
        "structured": profile.get("structured") or {},
        "version": profile.get("version") or 1,
    }
