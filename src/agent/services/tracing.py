"""Langfuse client for this process. Missing keys mean traces stay in app logs."""

from __future__ import annotations

import os

from langfuse import get_client

from common.logger import get_logger
from config import ENVIRONMENT, ActiveConfig

logger = get_logger("agent.sql")


def get_langfuse_client():
    """The process Langfuse client, or None when tracing is not configured."""
    if os.environ.get("PYTEST_CURRENT_TEST") or ENVIRONMENT.is_test:
        return None

    if not ActiveConfig.LANGFUSE_PUBLIC_KEY or not ActiveConfig.LANGFUSE_SECRET_KEY:
        return None
    return get_client()


def current_trace_id() -> str | None:
    """The Langfuse trace id for the turn that is running, if one is open."""
    client = get_langfuse_client()
    if client is None:
        return None
    getter = getattr(client, "get_current_trace_id", None)
    if not callable(getter):
        return None
    try:
        value = getter()
    except Exception:
        logger.warning("langfuse trace id unavailable", exc_info=True)
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def record_user_feedback(trace_id: str | None, thumbs: str, comment: str | None = None) -> None:
    """Write a `user_feedback` score on the turn's trace. Missing keys are a no-op."""
    client = get_langfuse_client()
    if client is None:
        return
    write_user_feedback(client, trace_id, thumbs, comment)


def write_user_feedback(client, trace_id: str | None, thumbs: str, comment: str | None = None) -> None:
    if client is None or not trace_id:
        return
    value = 1.0 if thumbs == "up" else 0.0
    try:
        client.create_score(
            name="user_feedback",
            value=value,
            trace_id=trace_id,
            score_id=f"user_feedback:{trace_id}",
            data_type="NUMERIC",
            comment=comment or None,
        )
        flush = getattr(client, "flush", None)
        if callable(flush):
            flush()
    except Exception:
        logger.warning("langfuse user_feedback score failed", exc_info=True)


def record_answer_grounding(trace_id: str | None, flags: list[str]) -> None:
    """Write an `answer_grounding` score on the turn's trace. Missing keys are a no-op."""
    client = get_langfuse_client()
    if client is None:
        return
    write_answer_grounding(client, trace_id, flags)


def write_answer_grounding(client, trace_id: str | None, flags: list[str]) -> None:
    """1.0 when every number is in the lookup, 0.0 when one is not. The reply text stays as streamed."""
    if client is None or not trace_id:
        return
    comment = " ".join(flag.strip() for flag in flags if flag and flag.strip()) or None
    if comment and len(comment) > 2000:
        comment = comment[:2000]
    try:
        client.create_score(
            name="answer_grounding",
            value=0.0 if flags else 1.0,
            trace_id=trace_id,
            score_id=f"answer_grounding:{trace_id}",
            data_type="NUMERIC",
            comment=comment,
        )
        flush = getattr(client, "flush", None)
        if callable(flush):
            flush()
    except Exception:
        logger.warning("langfuse answer_grounding score failed", exc_info=True)
