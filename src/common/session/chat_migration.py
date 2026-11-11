"""Copy chats that still live in Redis or only in checkpoints into ai_chatbot.

Each step is safe to run again. Rows already stored are left as they are.
A Redis miss does not stop the chat schema from opening.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime

from common.logger import get_logger
from common.schemas.session import SidebarSession
from common.services.app_clock import AppClock
from common.session.id_validation import safe_thread_id, safe_user_id
from config import ActiveConfig

logger = get_logger("session.migration")

_lock = threading.Lock()
_sidebar_done = False
_checkpoints_done = False


def migrate_redis_chats(pool, postgres_saver=None) -> None:
    """Copy the Redis sidebar, then any Redis transcript that Postgres does not have."""
    global _sidebar_done, _checkpoints_done
    with _lock:
        if not _sidebar_done:
            try:
                _copy_redis_sidebar(pool)
                _sidebar_done = True
            except Exception:
                logger.warning("redis sidebar copy failed", exc_info=True)
        if postgres_saver is not None and not _checkpoints_done:
            try:
                _copy_redis_checkpoints(pool, postgres_saver)
                _checkpoints_done = True
            except Exception:
                logger.warning("redis checkpoint copy failed", exc_info=True)
        try:
            _backfill_conversation_sessions(pool)
        except Exception:
            logger.warning("conversation_sessions backfill failed", exc_info=True)


def _copy_redis_sidebar(pool) -> None:
    if not ActiveConfig.REDIS_URL:
        return
    import redis

    client = redis.Redis.from_url(ActiveConfig.REDIS_URL, decode_responses=True)
    try:
        prefix = (ActiveConfig.CACHE_KEY_PREFIX or "").rstrip(":")
        marker = f"{prefix}:chat:sidebar:" if prefix else "chat:sidebar:"
        pending: list[tuple[str, SidebarSession]] = []
        for key in client.scan_iter(match=f"{marker}*", count=200):
            if not isinstance(key, str) or not key.startswith(marker):
                continue
            user_id = key[len(marker) :]
            if safe_user_id(user_id) is None:
                continue
            stored = _decode_cache(client.get(key))
            if not isinstance(stored, list):
                continue
            for item in stored:
                if not isinstance(item, dict):
                    continue
                row = SidebarSession.from_row(item)
                if row is None or safe_thread_id(row.session_id) is None:
                    continue
                pending.append((user_id, row))
        if not pending:
            return
        write_conversations = _can_write_conversations(pool)
        with pool.connection() as conn:
            for user_id, row in pending:
                created = _parse_time(row.created_at)
                active = _parse_time(row.last_active)
                conn.execute(
                    """
                    INSERT INTO chat_sessions (session_id, user_id, title, user_turns, created_at, last_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    (row.session_id, user_id, row.title or "Chat", row.user_turns, created, active),
                )
                if write_conversations:
                    conn.execute(
                        """
                        INSERT INTO conversation_sessions (session_id, created_at, last_active, turn_count)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (session_id) DO NOTHING
                        """,
                        (row.session_id, created, active, row.user_turns),
                    )
            _commit(conn)
        logger.info("Copied %s Redis sidebar rows into ai_chatbot", len(pending))
    finally:
        client.close()


def _copy_redis_checkpoints(pool, postgres_saver) -> None:
    if not ActiveConfig.REDIS_URL:
        return
    from agent.checkpointer.redis_checkpoint_saver import RedisCheckpointSaver

    redis_saver = RedisCheckpointSaver(
        redis_url=ActiveConfig.REDIS_URL,
        ttl={"default_ttl": 60 * 24, "refresh_on_read": True},
    )
    try:
        redis_saver.setup()
        existing = _existing_thread_ids(pool)
        latest = {}
        for item in redis_saver.list(None):
            thread_id = str((item.config.get("configurable") or {}).get("thread_id") or "")
            if not thread_id or thread_id in existing:
                continue
            checkpoint_id = str(item.checkpoint.get("id") or "")
            current = latest.get(thread_id)
            if current is None or checkpoint_id > str(current.checkpoint.get("id") or ""):
                latest[thread_id] = item
        copied = 0
        for item in latest.values():
            configurable = dict(item.config.get("configurable") or {})
            configurable.setdefault("checkpoint_ns", "")
            try:
                postgres_saver.put(
                    {"configurable": configurable},
                    item.checkpoint,
                    item.metadata,
                    item.checkpoint.get("channel_versions") or {},
                )
            except Exception:
                logger.warning("could not copy redis checkpoint %s", configurable.get("thread_id"), exc_info=True)
                continue
            copied += 1
        if copied:
            logger.info("Copied %s Redis checkpoints into ai_chatbot", copied)
    finally:
        client = getattr(redis_saver, "_redis", None)
        if client is not None and getattr(redis_saver, "_owns_its_client", False):
            client.close()


def _backfill_conversation_sessions(pool) -> None:
    if not _can_write_conversations(pool):
        logger.warning(
            "ai_chatbot.conversation_sessions is not writable by the chatbot role; backfill skipped"
        )
        return
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO conversation_sessions (session_id, created_at, last_active, turn_count)
            SELECT session_id, created_at, last_active, user_turns
            FROM chat_sessions
            ON CONFLICT (session_id) DO NOTHING
            """
        )
        if _regclass(conn, "checkpoints") is not None:
            conn.execute(
                """
                INSERT INTO conversation_sessions (session_id, created_at, last_active, turn_count)
                SELECT DISTINCT thread_id, now(), now(), 0
                FROM checkpoints
                ON CONFLICT (session_id) DO NOTHING
                """
            )
        _commit(conn)


def _existing_thread_ids(pool) -> set[str]:
    with pool.connection() as conn:
        if _regclass(conn, "checkpoints") is None:
            _commit(conn)
            return set()
        rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints").fetchall()
        _commit(conn)
    found = set()
    for row in rows:
        thread_id = row["thread_id"] if isinstance(row, dict) else row[0]
        if isinstance(thread_id, str) and thread_id:
            found.add(thread_id)
    return found


def _can_write_conversations(pool) -> bool:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT to_regclass('conversation_sessions') AS reg"
        ).fetchone()
        reg = row.get("reg") if isinstance(row, dict) else row[0]
        if reg is None:
            _commit(conn)
            return False
        allowed = conn.execute(
            "SELECT has_table_privilege('conversation_sessions', 'INSERT') AS ok"
        ).fetchone()
        _commit(conn)
    return bool(allowed["ok"] if isinstance(allowed, dict) else allowed[0])


def _regclass(conn, name: str):
    row = conn.execute("SELECT to_regclass(%s) AS reg", (name,)).fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get("reg")
    return row[0]


def _decode_cache(raw: str | None):
    if not isinstance(raw, str) or not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and "v" in payload:
        return payload["v"]
    return payload


def _parse_time(value: str) -> datetime:
    text = value.strip() if isinstance(value, str) else ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if text:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=AppClock.utcnow().tzinfo)
    return AppClock.utcnow()


def _commit(conn) -> None:
    if not getattr(conn, "autocommit", False):
        conn.commit()
