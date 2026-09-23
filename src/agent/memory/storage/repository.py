"""In-process memory tables. Postgres implements the same methods."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from agent.memory.models.column_map import ColumnSpec, seed_map
from agent.memory.read.scoring import as_datetime
from agent.memory.models.types import (
    MemoryRecord,
    MemorySettings,
    copy_record,
    utcnow,
)


def _tokens(text: str) -> set[str]:
    return {word for word in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if word}


def token_similarity(query: str, content: str) -> float:
    left = _tokens(query)
    right = _tokens(content)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class InMemoryRepository:
    """The durable operations, held in process for tests and local fakes."""

    def __init__(self) -> None:
        self._rows: dict[str, MemoryRecord] = {}
        self._events: list[dict[str, Any]] = []
        self._settings: dict[str, MemorySettings] = {}
        self._profiles: dict[str, dict[str, Any]] = {}
        self._columns = seed_map()
        self._event_seq = 1
        self._lock = threading.RLock()

    def transaction(self):
        return self._lock

    def columns(self) -> dict[str, ColumnSpec]:
        return dict(self._columns)

    def rename_column(self, logical: str, physical: str) -> None:
        with self._lock:
            spec = self._columns[logical]
            self._columns[logical] = ColumnSpec(
                logical_col=spec.logical_col,
                physical_col=physical,
                domain=spec.domain,
                value_type=spec.value_type,
                filter_key=spec.filter_key,
                slot=spec.slot,
                cluster=spec.cluster,
                exclusive=spec.exclusive,
            )

    def get(self, user_id: str, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._rows.get(memory_id)
            if row is None or row.user_id != user_id:
                return None
            return copy_record(row)

    def get_active_slot(self, user_id: str, slot: str) -> MemoryRecord | None:
        with self._lock:
            for row in self._rows.values():
                if row.user_id == user_id and row.slot == slot and row.status == "active":
                    return copy_record(row)
            return None

    def insert(self, record: MemoryRecord) -> MemoryRecord:
        with self._lock:
            self._rows[record.id] = copy_record(record)
            return copy_record(record)

    def update(self, record: MemoryRecord) -> None:
        with self._lock:
            current = self._rows.get(record.id)
            if current is None or current.user_id != record.user_id:
                raise KeyError(record.id)
            self._rows[record.id] = copy_record(record)

    def search(
        self,
        user_id: str,
        *,
        query: str | None = None,
        embedding: list[float] | None = None,
        status: str | None = "active",
        clusters: list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
        now: datetime | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        moment = now or utcnow()
        with self._lock:
            found: list[tuple[MemoryRecord, float]] = []
            for row in self._rows.values():
                if row.user_id != user_id:
                    continue
                if status is not None and row.status != status:
                    continue
                if clusters is not None and row.cluster not in clusters:
                    continue
                if row.status == "active" and row.expires_at is not None and row.expires_at <= moment:
                    continue
                score = 0.0
                if embedding and row.embedding:
                    score = cosine(embedding, row.embedding)
                elif query:
                    score = token_similarity(query, row.content)
                found.append((copy_record(row), score))
        found.sort(key=lambda pair: (pair[1], pair[0].updated_at), reverse=True)
        return found[offset : offset + limit]

    def list_active(self, user_id: str, *, now: datetime | None = None) -> list[MemoryRecord]:
        moment = now or utcnow()
        with self._lock:
            rows = []
            for row in self._rows.values():
                if row.user_id != user_id or row.status != "active":
                    continue
                if row.expires_at is not None and row.expires_at <= moment:
                    continue
                rows.append(copy_record(row))
        return rows

    def list_all(self, user_id: str) -> list[MemoryRecord]:
        with self._lock:
            return [copy_record(row) for row in self._rows.values() if row.user_id == user_id]

    def list_user_ids(self) -> list[str]:
        with self._lock:
            return sorted({row.user_id for row in self._rows.values()})

    def touch(self, memory_ids: list[str], *, now: datetime | None = None) -> None:
        moment = now or utcnow()
        with self._lock:
            for memory_id in memory_ids:
                row = self._rows.get(memory_id)
                if row is None:
                    continue
                row.last_accessed_at = moment
                row.access_count += 1

    def hard_delete_status(self, *, status: str, older_than: datetime) -> int:
        with self._lock:
            doomed = [
                row.id
                for row in self._rows.values()
                if row.status == status and row.updated_at < older_than
            ]
            for memory_id in doomed:
                self._rows.pop(memory_id, None)
            return len(doomed)

    def add_event(
        self,
        user_id: str,
        memory_id: str | None,
        event: str,
        actor: str,
        detail: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            row = {
                "id": self._event_seq,
                "user_id": user_id,
                "memory_id": memory_id,
                "event": event,
                "actor": actor,
                "detail": dict(detail or {}),
                "created_at": now or utcnow(),
            }
            self._event_seq += 1
            self._events.append(row)
            return dict(row, detail=dict(row["detail"]))

    def count_events(self, user_id: str, event: str) -> int:
        with self._lock:
            return sum(
                1 for item in self._events if item["user_id"] == user_id and item["event"] == event
            )

    def decayed_recently(self, memory_id: str, *, since: datetime) -> bool:
        with self._lock:
            for item in reversed(self._events):
                if item["memory_id"] != memory_id or not item["detail"].get("decay"):
                    continue
                created = as_datetime(item["created_at"], fallback=since)
                if created >= since:
                    return True
            return False

    def latest_open_contradiction(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in reversed(self._events):
                if (
                    item["user_id"] == user_id
                    and item["event"] == "contradiction_flagged"
                    and not item["detail"].get("asked")
                ):
                    return dict(item, detail=dict(item["detail"]))
            return None

    def mark_event(self, event_id: int, **detail: Any) -> None:
        with self._lock:
            for item in self._events:
                if item["id"] == event_id:
                    item["detail"].update(detail)
                    return

    def get_settings(self, user_id: str) -> MemorySettings:
        with self._lock:
            found = self._settings.get(user_id)
            if found is None:
                return MemorySettings(user_id=user_id)
            return found.copy()

    def save_settings(self, settings: MemorySettings) -> None:
        with self._lock:
            self._settings[settings.user_id] = settings.copy()

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            profile = self._profiles.get(user_id)
            if profile is None:
                return None
            return {
                "user_id": user_id,
                "summary": profile["summary"],
                "structured": dict(profile["structured"]),
                "version": profile["version"],
                "updated_at": profile["updated_at"],
            }

    def save_profile(
        self,
        user_id: str,
        summary: str,
        structured: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> None:
        with self._lock:
            current = self._profiles.get(user_id)
            version = 1 if current is None else int(current["version"]) + 1
            self._profiles[user_id] = {
                "summary": summary,
                "structured": dict(structured),
                "version": version,
                "updated_at": now or utcnow(),
            }


def new_id() -> str:
    return str(uuid.uuid4())
