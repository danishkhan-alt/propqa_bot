"""Thumbs votes for a chat turn. One row per session and turn, in the chatbot database."""

from __future__ import annotations

import os
import threading
from typing import Protocol

from psycopg.rows import dict_row

from common.db import close_pool, get_pool
from common.logger import get_logger
from config import ActiveConfig

logger = get_logger("feedback")

POOL_NAME = "feedback"

DDL = """
CREATE TABLE IF NOT EXISTS chat_feedback (
    session_id  text NOT NULL,
    turn_id     text NOT NULL,
    thumbs      text NOT NULL CHECK (thumbs IN ('up', 'down')),
    comment     text,
    trace_id    text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, turn_id)
);
"""

_UPSERT = """
INSERT INTO chat_feedback (session_id, turn_id, thumbs, comment, trace_id)
VALUES (%(session_id)s, %(turn_id)s, %(thumbs)s, %(comment)s, %(trace_id)s)
ON CONFLICT (session_id, turn_id) DO UPDATE
SET thumbs = EXCLUDED.thumbs,
    comment = COALESCE(EXCLUDED.comment, chat_feedback.comment),
    trace_id = COALESCE(EXCLUDED.trace_id, chat_feedback.trace_id),
    updated_at = now()
"""

_store: PostgresFeedbackStore | None = None
_lock = threading.Lock()


class FeedbackStore(Protocol):
    def save(
        self,
        *,
        session_id: str,
        turn_id: str,
        thumbs: str,
        comment: str | None,
        trace_id: str | None,
    ) -> None: ...

    def votes_for(self, session_id: str) -> dict[str, str]: ...

    def trace_for(self, session_id: str, turn_id: str) -> str | None: ...


class MemoryFeedbackStore:
    """In-process votes. Tests use this so a request never opens the chatbot database."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    def save(
        self,
        *,
        session_id: str,
        turn_id: str,
        thumbs: str,
        comment: str | None,
        trace_id: str | None,
    ) -> None:
        key = (session_id, turn_id)
        current = self.rows.get(key) or {}
        self.rows[key] = {
            "thumbs": thumbs,
            "comment": comment if comment is not None else current.get("comment"),
            "trace_id": trace_id or current.get("trace_id"),
        }

    def votes_for(self, session_id: str) -> dict[str, str]:
        return {turn_id: row["thumbs"] for (session, turn_id), row in self.rows.items() if session == session_id}

    def trace_for(self, session_id: str, turn_id: str) -> str | None:
        row = self.rows.get((session_id, turn_id))
        if row is None:
            return None
        return row.get("trace_id")


class PostgresFeedbackStore:
    def __init__(self, pool) -> None:
        self._pool = pool

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(DDL)
            conn.commit()

    def save(
        self,
        *,
        session_id: str,
        turn_id: str,
        thumbs: str,
        comment: str | None,
        trace_id: str | None,
    ) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                _UPSERT,
                {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "thumbs": thumbs,
                    "comment": comment,
                    "trace_id": trace_id,
                },
            )
            conn.commit()

    def votes_for(self, session_id: str) -> dict[str, str]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT turn_id, thumbs FROM chat_feedback WHERE session_id = %s",
                (session_id,),
            ).fetchall()
        return {row["turn_id"]: row["thumbs"] for row in rows}

    def trace_for(self, session_id: str, turn_id: str) -> str | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT trace_id FROM chat_feedback WHERE session_id = %s AND turn_id = %s",
                (session_id, turn_id),
            ).fetchone()
        if not row:
            return None
        trace_id = row["trace_id"]
        return trace_id if isinstance(trace_id, str) and trace_id.strip() else None


def get_feedback_store() -> PostgresFeedbackStore:
    """The chatbot-database store, created on first use."""
    global _store
    with _lock:
        if _store is not None:
            return _store
        pool = get_pool(
            POOL_NAME,
            min_size=ActiveConfig.CHAT_DB_POOL_MIN,
            max_size=ActiveConfig.CHAT_DB_POOL_MAX,
            connect_kwargs={"row_factory": dict_row},
        )
        store = PostgresFeedbackStore(pool)
        try:
            store.ensure_schema()
        except Exception:
            close_pool(POOL_NAME)
            raise
        _store = store
        return _store


def feedback_store_for(request) -> FeedbackStore | None:
    """The store on the app, or the chatbot database outside tests."""
    store = getattr(request.app.state, "feedback_store", None)
    if store is not None:
        return store
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        return get_feedback_store()
    except Exception:
        logger.warning("chat_feedback store unavailable", exc_info=True)
        return None


def attach_votes(turns: list[dict], votes: dict[str, str]) -> None:
    for turn in turns:
        vote = votes.get(str(turn.get("turn_id") or ""))
        turn["thumbs_up"] = vote == "up"
        turn["thumbs_down"] = vote == "down"
