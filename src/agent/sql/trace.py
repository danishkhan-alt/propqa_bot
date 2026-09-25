"""App log and Langfuse tool span for one SQL attempt, including every returned row."""

from __future__ import annotations

from typing import Any

from common.logger import get_logger

logger = get_logger("agent.sql")


def trace_sql_attempt(payload: dict[str, Any], client=None) -> None:
    """Record the statement, the columns, and each row that came back."""
    logger.info("sql.execute", extra={"extra_data": payload})
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            name="sql.execute",
            as_type="tool",
            input={
                "sql": payload.get("sql"),
                "params": payload.get("params"),
                "purpose": payload.get("purpose"),
                "domain_ids": payload.get("domain_ids"),
                "attempt": payload.get("attempt"),
            },
            metadata={
                "domain_ids": payload.get("domain_ids"),
                "attempt": payload.get("attempt"),
                "row_count": payload.get("row_count"),
                "truncated": payload.get("truncated"),
                "duration_ms": payload.get("duration_ms"),
            },
        ) as observation:
            observation.update(
                output={
                    "columns": payload.get("columns"),
                    "rows": payload.get("rows"),
                    "row_count": payload.get("row_count"),
                    "truncated": payload.get("truncated"),
                    "duration_ms": payload.get("duration_ms"),
                    "error": payload.get("error"),
                    "status": payload.get("status"),
                },
                level=_level(payload.get("status")),
            )
    except Exception as exc:
        logger.warning(
            "sql.execute trace was not sent",
            extra={"extra_data": {"error": exc.__class__.__name__}},
        )


def _level(status: str | None) -> str:
    if status == "failed":
        return "ERROR"
    if status == "empty":
        return "WARNING"
    return "DEFAULT"
