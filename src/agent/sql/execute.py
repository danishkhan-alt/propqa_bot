"""Run one guarded SELECT against the warehouse and return the rows."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SqlFailed(Exception):
    """The warehouse rejected the statement. The message is safe to log."""


@dataclass(frozen=True)
class SqlPage:
    """Rows the statement actually returned, already capped."""

    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    duration_ms: int


def run_against_warehouse(sql: str) -> SqlPage:
    """Execute `sql` on the warehouse pool. The caller has already guarded it."""
    from common.db import get_pool, warehouse_conninfo
    from config import ActiveConfig

    pool = get_pool(
        "warehouse",
        warehouse_conninfo(),
        min_size=1,
        max_size=min(ActiveConfig.CHAT_DB_POOL_MAX, 4),
        connect_kwargs={"row_factory": dict_row},
    )
    with pool.connection() as connection:
        return fetch_readonly(
            connection,
            sql,
            timeout_ms=ActiveConfig.SQL_TIMEOUT_MS,
            search_path=ActiveConfig.DB_SEARCH_PATH,
            row_cap=ActiveConfig.SQL_ROW_CAP,
        )


def fetch_readonly(connection, sql: str, *, timeout_ms: int, search_path: str, row_cap: int) -> SqlPage:
    """One read-only transaction. Returns at most `row_cap` rows."""
    timeout = _timeout_ms(timeout_ms)
    path = _search_path(search_path)
    started = time.perf_counter()
    try:
        with connection.transaction():
            connection.execute("SET LOCAL transaction_read_only = on")
            connection.execute(f"SET LOCAL statement_timeout = {timeout}")
            connection.execute(f"SET LOCAL search_path TO {path}")
            cursor = connection.execute(sql)
            fetched = cursor.fetchall()
            columns = [column.name for column in cursor.description] if cursor.description else []
    except Exception as exc:
        raise SqlFailed(_safe_db_error(exc)) from exc
    duration_ms = int((time.perf_counter() - started) * 1000)
    visible = fetched[:row_cap]
    rows = [{column: json_ready(row.get(column)) for column in columns} for row in visible]
    return SqlPage(
        columns=columns,
        rows=rows,
        truncated=len(fetched) > row_cap,
        duration_ms=duration_ms,
    )


def json_ready(value: Any) -> Any:
    """A log and a prompt can both carry this value."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return None
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return str(value)


def _timeout_ms(timeout_ms: int) -> int:
    try:
        value = int(timeout_ms)
    except (TypeError, ValueError):
        return 15_000
    if value < 1 or value > 120_000:
        return 15_000
    return value


def _search_path(raw: str) -> str:
    parts = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not parts or any(_IDENTIFIER.match(part) is None for part in parts):
        raise SqlFailed("Warehouse search_path is not a list of identifiers")
    return ", ".join(parts)


def _safe_db_error(exc: Exception) -> str:
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None) if diag is not None else None
    text = " ".join(str(primary or exc.__class__.__name__).split())
    lowered = text.lower()
    if "://" in text or "password" in lowered or "secret" in lowered:
        return exc.__class__.__name__
    return text[:300]
