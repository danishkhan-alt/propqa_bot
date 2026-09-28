"""The process-wide account repository, opened on first use."""

from __future__ import annotations

import threading

from psycopg.rows import dict_row

from auth.storage import PostgresUserRepository, UserRepository
from common.db import close_pool, get_pool
from config import ActiveConfig

POOL_NAME = "auth"

_repository: UserRepository | None = None
_lock = threading.Lock()


def get_user_repository() -> UserRepository:
    """Accounts live in the chatbot database next to long-term memory."""
    global _repository
    with _lock:
        if _repository is None:
            _repository = _open_postgres_repository()
        return _repository


def set_user_repository(repository: UserRepository | None) -> None:
    global _repository
    with _lock:
        _repository = repository


def close_user_repository() -> None:
    set_user_repository(None)
    close_pool(POOL_NAME)


def _open_postgres_repository() -> PostgresUserRepository:
    pool = get_pool(
        POOL_NAME,
        min_size=ActiveConfig.CHAT_DB_POOL_MIN,
        max_size=ActiveConfig.CHAT_DB_POOL_MAX,
        connect_kwargs={"row_factory": dict_row},
    )
    repository = PostgresUserRepository(pool)
    try:
        repository.ensure_schema()
    except Exception:
        close_pool(POOL_NAME)
        raise
    return repository
