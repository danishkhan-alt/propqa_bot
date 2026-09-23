from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

from common.logger import get_logger

logger = get_logger("common.db")

_pools: dict[str, ConnectionPool] = {}
_lock = threading.Lock()


def build_conninfo(
    *,
    host: str,
    port: int,
    dbname: str,
    user: str = "",
    password: str = "",
    sslmode: str = "disable",
) -> str:
    """Libpq connection string. A directory host is the local socket.

    Empty user and password are left out so local peer auth can use the OS user.
    """
    params: dict[str, Any] = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "sslmode": sslmode,
    }
    if user:
        params["user"] = user
    if password:
        params["password"] = password
    return make_conninfo(**params)


def warehouse_conninfo() -> str:
    """Connection string for the read-only warehouse. Not the chatbot database."""
    from config import ActiveConfig

    return build_conninfo(
        host=ActiveConfig.AUDIT_DB_HOST,
        port=ActiveConfig.AUDIT_DB_PORT,
        dbname=ActiveConfig.AUDIT_DB_DATABASE,
        user=ActiveConfig.AUDIT_DB_USERNAME,
        password=ActiveConfig.AUDIT_DB_PASSWORD,
        sslmode=ActiveConfig.AUDIT_DB_SSLMODE,
    )


def chat_conninfo() -> str:
    """Connection string for the chatbot database, never the warehouse."""
    from config import ActiveConfig

    return build_conninfo(
        host=ActiveConfig.CHAT_DB_HOST,
        port=ActiveConfig.CHAT_DB_PORT,
        dbname=ActiveConfig.CHAT_DB_NAME,
        user=ActiveConfig.CHAT_DB_USER,
        password=ActiveConfig.CHAT_DB_PASSWORD,
        sslmode=ActiveConfig.CHAT_DB_SSLMODE,
    )


def get_pool(
    name: str,
    conninfo: str | None = None,
    *,
    min_size: int = 1,
    max_size: int = 10,
    timeout: float = 30,
    max_idle: float = 300,
    max_lifetime: float = 1800,
    connect_kwargs: Mapping[str, Any] | None = None,
) -> ConnectionPool:
    """Process-wide pool for `name`. The first open wins; later calls reuse it.

    `connect_kwargs` are passed to every connection (autocommit, row factory).
    Use a different `name` when those settings differ.
    """
    if not name.strip():
        raise ValueError("pool name is required")

    with _lock:
        existing = _pools.get(name)
        if existing is not None and not existing.closed:
            return existing

        info = conninfo if conninfo is not None else chat_conninfo()
        pool = ConnectionPool(
            conninfo=info,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            max_idle=max_idle,
            max_lifetime=max_lifetime,
            kwargs=dict(connect_kwargs or {}),
            open=False,
            name=name,
            check=ConnectionPool.check_connection,
        )
        pool.open(wait=True, timeout=timeout)
        _pools[name] = pool

    logger.info("Opened Postgres pool %s", name)
    return pool


def close_pool(name: str) -> None:
    with _lock:
        pool = _pools.pop(name, None)
    if pool is not None and not pool.closed:
        pool.close()


def close_pools() -> None:
    with _lock:
        names = list(_pools)
    for name in names:
        close_pool(name)
