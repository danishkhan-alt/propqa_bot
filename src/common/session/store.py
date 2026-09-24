"""Sidebar list of chats, stored in the shared cache."""

from __future__ import annotations

from dataclasses import dataclass

from common.cache import get_cache
from common.services.datetime import DateTimeUtils
from common.session.identity import safe_thread_id, safe_user_id

TTL_SECONDS = 60 * 60 * 24 * 7
_MAX_ROWS = 50


@dataclass(slots=True)
class Session:
    """One chat the sidebar can list and reopen."""

    session_id: str
    last_active: str
    created_at: str
    user_turns: int
    title: str

    @classmethod
    def from_row(cls, row: dict) -> Session | None:
        session_id = row.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        return cls(
            session_id=session_id,
            last_active=_text(row.get("last_active")),
            created_at=_text(row.get("created_at")),
            user_turns=_count(row.get("user_turns")),
            title=_text(row.get("title")),
        )

    def to_row(self) -> dict:
        return {
            "session_id": self.session_id,
            "last_active": self.last_active,
            "created_at": self.created_at,
            "user_turns": self.user_turns,
            "title": self.title,
        }


def note_session(user_id: str, session_id: str, message: str) -> None:
    """Remember a chat so the sidebar can list it."""
    owner = safe_user_id(user_id) or user_id
    if not owner or not session_id:
        return
    now = DateTimeUtils.utcnow().isoformat()
    title = " ".join(message.split())[:80] or "Chat"
    rows = _load(owner)
    for row in rows:
        if row.session_id == session_id:
            row.last_active = now
            row.user_turns += 1
            if not row.title.strip():
                row.title = title
            _save(owner, rows)
            _remember_owner(session_id, owner)
            return
    rows.insert(
        0,
        Session(
            session_id=session_id,
            last_active=now,
            created_at=now,
            user_turns=1,
            title=title,
        ),
    )
    _save(owner, rows[:_MAX_ROWS])
    _remember_owner(session_id, owner)


def sessions_for(user_id: str | None, limit: int = 30) -> list[Session]:
    owner = safe_user_id(user_id)
    if owner is None:
        return []
    return _load(owner)[: max(0, min(limit, _MAX_ROWS))]


def detach_session(session_id: str) -> str | None:
    """Drop the sidebar row. Returns the thread id when the id is usable."""
    thread_id = safe_thread_id(session_id)
    if thread_id is None:
        return None
    owner = get_cache().get(_owner_key(thread_id), None)
    if isinstance(owner, str):
        kept = [row for row in _load(owner) if row.session_id != thread_id]
        _save(owner, kept)
        get_cache().delete(_owner_key(thread_id))
    return thread_id


def _load(user_id: str) -> list[Session]:
    stored = get_cache().get(_sessions_key(user_id), None)
    if not isinstance(stored, list):
        return []
    rows = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        row = Session.from_row(item)
        if row is not None:
            rows.append(row)
    return rows


def _save(user_id: str, rows: list[Session]) -> None:
    get_cache().set(_sessions_key(user_id), [row.to_row() for row in rows], ttl=TTL_SECONDS)


def _remember_owner(session_id: str, owner: str) -> None:
    get_cache().set(_owner_key(session_id), owner, ttl=TTL_SECONDS)


def _sessions_key(user_id: str) -> str:
    return f"fe:sessions:{user_id}"


def _owner_key(session_id: str) -> str:
    return f"fe:session-owner:{session_id}"


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value
