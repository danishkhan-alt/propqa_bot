"""Memory records, working-memory frames, and the extraction contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

MEMORY_TYPES = ("profile", "preference", "semantic", "episodic", "goal", "ephemeral")
PROVENANCE = ("explicit", "inferred", "system", "summarized")
STATUSES = ("active", "superseded", "expired", "deleted", "contradicted")
DEFAULT_CLUSTERS = ("property_prefs", "budget", "location", "persona", "goal")
ALL_CLUSTERS = (*DEFAULT_CLUSTERS, "personal", "work", "travel")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class MemorySettings:
    user_id: str
    memory_enabled: bool = True
    allowed_clusters: tuple[str, ...] = DEFAULT_CLUSTERS
    retention_days: int | None = None

    def copy(self) -> MemorySettings:
        return replace(self, allowed_clusters=tuple(self.allowed_clusters))


@dataclass(slots=True)
class MemoryRecord:
    id: str
    user_id: str
    type: str
    cluster: str
    content: str
    confidence: float
    importance: float
    provenance: str
    slot: str | None = None
    structured: dict[str, Any] | None = None
    embedding: list[float] | None = None
    source_thread_id: str | None = None
    source_message_id: str | None = None
    status: str = "active"
    supersedes_id: str | None = None
    valid_from: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    last_accessed_at: datetime | None = None
    access_count: int = 0
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


def copy_record(record: MemoryRecord) -> MemoryRecord:
    structured = dict(record.structured) if record.structured else None
    embedding = list(record.embedding) if record.embedding else None
    return replace(record, structured=structured, embedding=embedding)


@dataclass(slots=True)
class MemoryOp:
    """One extractor decision. `noop` is dropped before insert."""

    op: str
    type: str
    cluster: str
    content: str
    provenance: str
    confidence: float
    importance: float
    slot: str | None = None
    structured: dict[str, Any] | None = None
    ttl_days: int | None = None
    target_memory_id: str | None = None
    evidence: str = ""
    source_thread_id: str | None = None
    source_message_id: str | None = None


def empty_frame() -> dict[str, Any]:
    return {
        "domain": "",
        "intent": "",
        "predicates": {},
        "projection": [],
        "order_by": [],
        "limit": None,
        "sql": "",
        "result_meta": {},
        "turn": 0,
    }


def clone_frame(frame: dict[str, Any] | None) -> dict[str, Any]:
    """Working memory is a plain dict so checkpoints and Redis can both store it."""
    if not frame:
        return empty_frame()
    predicates: dict[str, Any] = {}
    for key, value in (frame.get("predicates") or {}).items():
        predicates[key] = dict(value) if isinstance(value, dict) else value
    meta = dict(frame.get("result_meta") or {})
    if isinstance(meta.get("ids"), list):
        meta["ids"] = list(meta["ids"])
    return {
        "domain": frame.get("domain") or "",
        "intent": frame.get("intent") or "",
        "predicates": predicates,
        "projection": list(frame.get("projection") or []),
        "order_by": [list(pair) for pair in (frame.get("order_by") or [])],
        "limit": frame.get("limit"),
        "sql": frame.get("sql") or "",
        "result_meta": meta,
        "turn": int(frame.get("turn") or 0),
    }


def public_record(record: MemoryRecord, *, similarity: float = 0) -> dict[str, Any]:
    """Serializable view stored on graph state and returned from the store."""
    return {
        "id": record.id,
        "type": record.type,
        "cluster": record.cluster,
        "slot": record.slot,
        "content": record.content,
        "structured": dict(record.structured) if record.structured else None,
        "confidence": record.confidence,
        "importance": record.importance,
        "provenance": record.provenance,
        "status": record.status,
        "similarity": similarity,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }
