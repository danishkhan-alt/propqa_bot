"""One chat in the sidebar list, and how it is stored in the shared cache."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SidebarSession:
    """One chat the sidebar can list and reopen."""

    session_id: str
    last_active: str
    created_at: str
    user_turns: int
    title: str

    @classmethod
    def from_row(cls, row: dict) -> SidebarSession | None:
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


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value
