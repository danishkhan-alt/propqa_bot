"""Sidebar rows and conversation activity in schema ai_chatbot."""

from __future__ import annotations

import threading
from datetime import datetime

from psycopg.rows import dict_row

from common.db import chat_schema_connect_kwargs, close_pool, get_pool
from common.logger import get_logger
from common.schemas.session import SidebarSession
from common.services.app_clock import AppClock
from common.session.id_validation import safe_thread_id, safe_user_id

logger = get_logger("session.store")

POOL_NAME = "chat_sessions"
MAX_SIDEBAR_SESSIONS = 50

DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id   text PRIMARY KEY,
    user_id      text NOT NULL,
    title        text NOT NULL,
    user_turns   integer NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_active  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_sessions_user_last_active_idx
    ON chat_sessions (user_id, last_active DESC);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id   text PRIMARY KEY,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_active  timestamptz NOT NULL DEFAULT now(),
    turn_count   integer NOT NULL DEFAULT 0
);
"""

_UPSERT_CHAT = """
INSERT INTO chat_sessions (session_id, user_id, title, user_turns, created_at, last_active)
VALUES (%s, %s, %s, 1, %s, %s)
ON CONFLICT (session_id) DO UPDATE
SET last_active = EXCLUDED.last_active,
    user_turns = chat_sessions.user_turns + 1,
    title = CASE
        WHEN btrim(chat_sessions.title) = '' THEN EXCLUDED.title
        ELSE chat_sessions.title
    END
WHERE chat_sessions.user_id = EXCLUDED.user_id
RETURNING session_id
"""

_UPSERT_CONVERSATION = """
INSERT INTO conversation_sessions (session_id, created_at, last_active, turn_count)
VALUES (%s, %s, %s, 1)
ON CONFLICT (session_id) DO UPDATE
SET last_active = EXCLUDED.last_active,
    turn_count = conversation_sessions.turn_count + 1
"""

_TRIM = """
DELETE FROM chat_sessions
WHERE user_id = %s
  AND session_id IN (
      SELECT session_id FROM (
          SELECT session_id
          FROM chat_sessions
          WHERE user_id = %s
          ORDER BY last_active DESC
          OFFSET %s
      ) extra
  )
"""

_LIST = """
SELECT session_id, last_active, created_at, user_turns, title
FROM chat_sessions
WHERE user_id = %s
ORDER BY last_active DESC
LIMIT %s
"""

_ready = False
_conversation_writable = True
_lock = threading.Lock()


def chat_session_pool():
    """The chat-schema pool, with session tables created on first use."""
    global _ready, _conversation_writable
    from config import ActiveConfig

    pool = get_pool(
        POOL_NAME,
        min_size=ActiveConfig.CHAT_DB_POOL_MIN,
        max_size=ActiveConfig.CHAT_DB_POOL_MAX,
        connect_kwargs=chat_schema_connect_kwargs(row_factory=dict_row),
    )
    if _ready:
        return pool
    with _lock:
        if _ready:
            return pool
        try:
            with pool.connection() as conn:
                conn.execute(DDL)
                _conversation_writable = _conversation_is_writable(conn)
                conn.commit()
        except Exception:
            close_pool(POOL_NAME)
            raise
        if not _conversation_writable:
            logger.warning(
                "ai_chatbot.conversation_sessions is not writable. "
                "Its owner must run: GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON ai_chatbot.conversation_sessions TO the chatbot role"
            )
        from common.session.chat_migration import migrate_redis_chats

        migrate_redis_chats(pool)
        _ready = True
    return pool


def record_chat_session(user_id: str, session_id: str, message: str, *, pool=None) -> None:
    """Insert or bump one sidebar row, and the matching conversation row."""
    now = AppClock.utcnow()
    title = " ".join(message.split())[:80] or "Chat"
    target = pool if pool is not None else chat_session_pool()
    with target.connection() as conn:
        written = conn.execute(_UPSERT_CHAT, (session_id, user_id, title, now, now)).fetchone()
        if written is not None:
            if _conversation_writable:
                conn.execute(_UPSERT_CONVERSATION, (session_id, now, now))
            conn.execute(_TRIM, (user_id, user_id, MAX_SIDEBAR_SESSIONS))
        conn.commit()


def list_chat_sessions(user_id: str | None, limit: int = 30, *, pool=None) -> list[SidebarSession]:
    owner = safe_user_id(user_id)
    if owner is None:
        return []
    cap = max(0, min(limit, MAX_SIDEBAR_SESSIONS))
    if cap == 0:
        return []
    target = pool if pool is not None else chat_session_pool()
    with target.connection() as conn:
        rows = conn.execute(_LIST, (owner, cap)).fetchall()
        conn.commit()
    sessions = []
    for row in rows:
        item = row if isinstance(row, dict) else {
            "session_id": row[0],
            "last_active": row[1],
            "created_at": row[2],
            "user_turns": row[3],
            "title": row[4],
        }
        session = SidebarSession.from_row(
            {
                "session_id": item.get("session_id"),
                "last_active": _as_text(item.get("last_active")),
                "created_at": _as_text(item.get("created_at")),
                "user_turns": item.get("user_turns"),
                "title": _as_text(item.get("title")),
            }
        )
        if session is not None:
            sessions.append(session)
    return sessions


def remove_chat_session(session_id: str, *, pool=None) -> str | None:
    """Drop the sidebar and conversation rows. Returns the thread id when it is usable."""
    thread_id = safe_thread_id(session_id)
    if thread_id is None:
        return None
    target = pool if pool is not None else chat_session_pool()
    with target.connection() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE session_id = %s", (thread_id,))
        if _conversation_writable:
            conn.execute("DELETE FROM conversation_sessions WHERE session_id = %s", (thread_id,))
        conn.commit()
    return thread_id


def transfer_chat_session(session_id: str, from_owner: str, to_owner: str, *, pool=None) -> bool:
    """Move a chat to another owner, only if ``from_owner`` owns it now."""
    thread_id = safe_thread_id(session_id)
    source = safe_user_id(from_owner)
    target_owner = safe_user_id(to_owner)
    if thread_id is None or source is None or target_owner is None:
        return False
    target = pool if pool is not None else chat_session_pool()
    with target.connection() as conn:
        moved = conn.execute(
            """
            UPDATE chat_sessions SET user_id = %s
            WHERE session_id = %s AND user_id = %s
            RETURNING session_id
            """,
            (target_owner, thread_id, source),
        ).fetchone()
        if moved is None:
            conn.commit()
            return False
        conn.execute(
            """
            DELETE FROM chat_sessions
            WHERE user_id = %s
              AND session_id <> %s
              AND session_id IN (
                  SELECT session_id FROM (
                      SELECT session_id
                      FROM chat_sessions
                      WHERE user_id = %s AND session_id <> %s
                      ORDER BY last_active DESC
                      OFFSET %s
                  ) extra
              )
            """,
            (target_owner, thread_id, target_owner, thread_id, MAX_SIDEBAR_SESSIONS - 1),
        )
        conn.commit()
    return True


def _conversation_is_writable(conn) -> bool:
    """The table may exist but be owned by another role that has not granted writes."""
    row = conn.execute("SELECT to_regclass('conversation_sessions') AS reg").fetchone()
    if row is None or row.get("reg") is None:
        return False
    allowed = conn.execute(
        """
        SELECT has_table_privilege('conversation_sessions', 'INSERT') AS can_insert,
               has_table_privilege('conversation_sessions', 'UPDATE') AS can_update,
               has_table_privilege('conversation_sessions', 'DELETE') AS can_delete
        """
    ).fetchone()
    return bool(allowed["can_insert"] and allowed["can_update"] and allowed["can_delete"])


def _as_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else ""
