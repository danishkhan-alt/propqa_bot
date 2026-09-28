"""Sidebar list of chats, stored in the shared cache."""

from __future__ import annotations

from common.cache import get_cache
from common.schemas.session import SidebarSession
from common.services.app_clock import AppClock
from common.session.id_validation import safe_thread_id, safe_user_id

SESSION_TTL_SECONDS = 60 * 60 * 24 * 7
_MAX_SIDEBAR_SESSIONS = 50


def record_session_activity(user_id: str, session_id: str, message: str) -> None:
    """Remember a chat so the sidebar can list it."""
    owner = safe_user_id(user_id) or user_id
    if not owner or not session_id:
        return
    now = AppClock.utcnow().isoformat()
    title = " ".join(message.split())[:80] or "Chat"
    rows = _load_sessions(owner)
    for row in rows:
        if row.session_id == session_id:
            row.last_active = now
            row.user_turns += 1
            if not row.title.strip():
                row.title = title
            _save_sessions(owner, rows)
            _remember_owner(session_id, owner)
            return
    rows.insert(
        0,
        SidebarSession(
            session_id=session_id,
            last_active=now,
            created_at=now,
            user_turns=1,
            title=title,
        ),
    )
    _save_sessions(owner, rows[:_MAX_SIDEBAR_SESSIONS])
    _remember_owner(session_id, owner)


def list_user_sessions(user_id: str | None, limit: int = 30) -> list[SidebarSession]:
    owner = safe_user_id(user_id)
    if owner is None:
        return []
    return _load_sessions(owner)[: max(0, min(limit, _MAX_SIDEBAR_SESSIONS))]


def remove_sidebar_session(session_id: str) -> str | None:
    """Drop the sidebar row. Returns the thread id when the id is usable."""
    thread_id = safe_thread_id(session_id)
    if thread_id is None:
        return None
    owner = get_cache().get(_owner_key(thread_id), None)
    if isinstance(owner, str):
        kept = [row for row in _load_sessions(owner) if row.session_id != thread_id]
        _save_sessions(owner, kept)
        get_cache().delete(_owner_key(thread_id))
    return thread_id


def transfer_sidebar_session(session_id: str, from_owner: str, to_owner: str) -> bool:
    """Move a chat to another owner, only if ``from_owner`` owns it now."""
    thread_id = safe_thread_id(session_id)
    source = safe_user_id(from_owner)
    target = safe_user_id(to_owner)
    if thread_id is None or source is None or target is None:
        return False
    if get_cache().get(_owner_key(thread_id), None) != source:
        return False
    source_rows = _load_sessions(source)
    moved = next((row for row in source_rows if row.session_id == thread_id), None)
    if moved is None:
        return False
    _save_sessions(source, [row for row in source_rows if row.session_id != thread_id])
    target_rows = [row for row in _load_sessions(target) if row.session_id != thread_id]
    _save_sessions(target, [moved, *target_rows][:_MAX_SIDEBAR_SESSIONS])
    _remember_owner(thread_id, target)
    return True


def _load_sessions(user_id: str) -> list[SidebarSession]:
    stored = get_cache().get(_sessions_key(user_id), None)
    if not isinstance(stored, list):
        return []
    rows = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        row = SidebarSession.from_row(item)
        if row is not None:
            rows.append(row)
    return rows


def _save_sessions(user_id: str, rows: list[SidebarSession]) -> None:
    get_cache().set(_sessions_key(user_id), [row.to_row() for row in rows], ttl=SESSION_TTL_SECONDS)


def _remember_owner(session_id: str, owner: str) -> None:
    get_cache().set(_owner_key(session_id), owner, ttl=SESSION_TTL_SECONDS)


def _sessions_key(user_id: str) -> str:
    return f"fe:sessions:{user_id}"


def _owner_key(session_id: str) -> str:
    return f"fe:session-owner:{session_id}"
