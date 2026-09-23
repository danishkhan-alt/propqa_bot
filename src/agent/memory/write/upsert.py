"""Slot supersession, overlap merge, and contradiction flagging."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from agent.memory.safety.reject_unsafe import MemoryRejected, validate_memory
from agent.memory.write.filters import (
    merge_filters,
    same_filter,
    can_merge_filters,
)
from agent.memory.storage.repository import InMemoryRepository, new_id
from agent.memory.session.bootstrap import invalidate
from agent.memory.models.types import MemoryOp, MemoryRecord, utcnow
from common.logger import get_logger

logger = get_logger("agent.memory")

IMPORTANCE_FLOOR = 0.3


def write_memories(
    repository: InMemoryRepository,
    user_id: str,
    ops: list[MemoryOp],
    *,
    now: datetime | None = None,
    actor: str = "extractor",
) -> list[str]:
    """Apply a list of memory operations to the repository.

    Args:
        repository: The repository to apply the memory operations to.
        user_id: The user ID to apply the memory operations to.
        ops: The list of memory operations to apply.
        now: The current time.
        actor: The actor who is applying the memory operations.

    Returns:
        A list of memory IDs that were touched.

    Raises:
        MemoryRejected: If the memory operation is rejected.
    """

    moment = now or utcnow()
    touched: list[str] = []

    with repository.transaction():
        for op in ops:
            if op.op == "noop":
                continue
            if op.op != "delete" and op.importance < IMPORTANCE_FLOOR:
                continue
            try:
                cleaned = validate_memory(op, repository.columns())
            except MemoryRejected as exc:
                logger.info(
                    "memory.rejected",
                    extra={"extra_data": {"reason": str(exc), "user_id": user_id}},
                )
                continue
            if cleaned.op == "delete":
                touched.extend(_delete(repository, user_id, cleaned, moment, actor))
            elif cleaned.slot:
                touched.extend(_apply_slot(repository, user_id, cleaned, moment, actor))
            else:
                touched.extend(_apply_free(repository, user_id, cleaned, moment, actor))
    if touched:
        invalidate(user_id)
    return touched


def _apply_slot(
    repository, user_id, op: MemoryOp, now: datetime, actor: str
) -> list[str]:
    """Apply a slot memory operation to the repository.

    Args:
        repository: The repository to apply the memory operation to.
        user_id: The user ID to apply the memory operation to.
        op: The memory operation to apply.
        now: The current time.
        actor: The actor who is applying the memory operation.

    Returns:
        A list of memory IDs that were touched.

    Raises:
        MemoryRejected: If the memory operation is rejected.
    """

    existing = repository.get_active_slot(user_id, op.slot or "")

    if existing is None:
        return [_insert(repository, user_id, op, now, actor)]

    if same_filter(existing.structured, op.structured):
        _strengthen_repeat(existing, now)
        if op.type == "goal" or op.ttl_days:
            existing.expires_at = _expires(op, now)
        repository.update(existing)
        repository.add_event(
            user_id, existing.id, "updated", actor, {"repeat": True}, now
        )
        return [existing.id]

    if op.op != "update" and can_merge_filters(
        op.slot, existing.structured, op.structured
    ):
        return _merge(repository, user_id, existing, op, now, actor)

    if existing.provenance == "explicit" and op.provenance == "inferred":
        return _flag_contradiction(repository, user_id, existing, op, now, actor)

    if op.provenance == "explicit" or op.confidence > existing.confidence:
        return _supersede(repository, user_id, existing, op, now, actor)

    return _flag_contradiction(repository, user_id, existing, op, now, actor)


def _apply_free(
    repository, user_id, op: MemoryOp, now: datetime, actor: str
) -> list[str]:
    """Apply a free memory operation to the repository.
    
    Args:
        repository: The repository to apply the memory operation to.
        user_id: The user ID to apply the memory operation to.
        op: The memory operation to apply.
        now: The current time.
        actor: The actor who is applying the memory operation.

    Returns:
        A list of memory IDs that were touched.

    Raises:
        MemoryRejected: If the memory operation is rejected.
    """

    near = repository.search(user_id, query=op.content, limit=3, now=now)
    
    if near and near[0][1] > 0.92:

        record = near[0][0]
        _strengthen_repeat(record, now)
        repository.update(record)
        repository.add_event(
            user_id, record.id, "updated", actor, {"repeat": True}, now
        )
        return [record.id]
    
    for record, score in near:
        if _is_negation(record.content, op.content, score):
            if op.provenance == "explicit" or op.confidence > record.confidence:
                return _supersede(repository, user_id, record, op, now, actor)
            return _flag_contradiction(repository, user_id, record, op, now, actor)
    
    return [_insert(repository, user_id, op, now, actor)]


def _merge(
    repository, user_id, existing: MemoryRecord, op: MemoryOp, now: datetime, actor: str
) -> list[str]:
    _mark_superseded(repository, user_id, existing, now, actor)
    merged = merge_filters(existing.structured or {}, op.structured or {})
    values = merged.get("val")
    shown = (
        ", ".join(str(value) for value in values)
        if isinstance(values, list)
        else values
    )
    created = MemoryOp(
        op="add",
        type="semantic",
        cluster=op.cluster,
        slot=op.slot,
        content=f"Open to {shown} for {op.slot}",
        structured=merged,
        provenance="inferred",
        confidence=0.6,
        importance=max(existing.importance, op.importance),
        evidence=op.evidence,
        source_thread_id=op.source_thread_id,
        source_message_id=op.source_message_id,
    )
    memory_id = _insert(
        repository, user_id, created, now, actor, supersedes_id=existing.id
    )
    return [existing.id, memory_id]


def _supersede(
    repository, user_id, existing, op: MemoryOp, now: datetime, actor: str
) -> list[str]:
    _mark_superseded(repository, user_id, existing, now, actor)
    memory_id = _insert(repository, user_id, op, now, actor, supersedes_id=existing.id)
    return [existing.id, memory_id]


def _flag_contradiction(
    repository, user_id, existing: MemoryRecord, op: MemoryOp, now: datetime, actor: str
) -> list[str]:
    existing.confidence = max(0.2, existing.confidence - 0.15)
    repository.update(existing)
    held = _insert(repository, user_id, op, now, actor, status="contradicted")
    prompt = f"Still going by “{existing.content}”, or has that changed?"
    repository.add_event(
        user_id,
        existing.id,
        "contradiction_flagged",
        actor,
        {"prompt": prompt, "asked": False, "new_id": held},
        now,
    )
    return [existing.id, held]


def _delete(repository, user_id, op: MemoryOp, now: datetime, actor: str) -> list[str]:
    rows: list[MemoryRecord] = []
    if op.target_memory_id:
        found = repository.get(user_id, op.target_memory_id)
        if found is not None and found.status == "active":
            rows.append(found)
    elif op.slot:
        found = repository.get_active_slot(user_id, op.slot)
        if found is not None:
            rows.append(found)
    touched = []
    for row in rows:
        row.status = "deleted"
        row.embedding = None
        row.updated_at = now
        repository.update(row)
        repository.add_event(
            user_id, row.id, "deleted_by_user", actor, {"evidence": op.evidence}, now
        )
        touched.append(row.id)
    return touched


def _mark_superseded(
    repository, user_id, existing: MemoryRecord, now: datetime, actor: str
) -> None:
    """retires an old memory when a newer one replaces it."""
    
    existing.status = "superseded"
    existing.updated_at = now
    repository.update(existing)
    repository.add_event(user_id, existing.id, "superseded", actor, {}, now)


def _insert(
    repository,
    user_id: str,
    op: MemoryOp,
    now: datetime,
    actor: str,
    *,
    status: str = "active",
    supersedes_id: str | None = None,
) -> str:
    record = MemoryRecord(
        id=new_id(),
        user_id=user_id,
        type=op.type,
        cluster=op.cluster,
        slot=op.slot,
        content=op.content,
        structured=dict(op.structured) if op.structured else None,
        confidence=op.confidence,
        importance=op.importance,
        provenance=op.provenance,
        source_thread_id=op.source_thread_id,
        source_message_id=op.source_message_id,
        status=status,
        supersedes_id=supersedes_id,
        expires_at=_expires(op, now),
        created_at=now,
        updated_at=now,
        valid_from=now,
    )
    repository.insert(record)
    repository.add_event(
        user_id,
        record.id,
        "created",
        actor,
        {"evidence": op.evidence, "op": op.op},
        now,
    )
    return record.id


def _strengthen_repeat(record: MemoryRecord, now: datetime) -> None:
    record.confidence = min(1.0, record.confidence + 0.05)
    record.updated_at = now
    record.access_count += 1


def _expires(op: MemoryOp, now: datetime) -> datetime | None:
    if op.ttl_days:
        return now + timedelta(days=int(op.ttl_days))
    if op.type == "ephemeral":
        return now + timedelta(days=7)
    if op.type == "goal":
        return now + timedelta(days=45)
    return None


def _is_negation(left: str, right: str, similarity: float) -> bool:
    overlap = _polarity_overlap(left, right)
    if similarity < 0.34 and overlap < 0.5:
        return False
    return _negative(left) != _negative(right) and overlap >= 0.5


def _negative(text: str) -> bool:
    import re

    return bool(
        re.search(
            r"\b(not|no|never|don't|do not|without|avoid|doesn't|does not)\b",
            text,
            re.I,
        )
    )


def _polarity_overlap(left: str, right: str) -> float:
    drop = {"not", "no", "never", "dont", "without", "avoid", "doesnt", "do", "does"}
    left_tokens = _stem_tokens(left) - drop
    right_tokens = _stem_tokens(right) - drop
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _stem_tokens(text: str) -> set[str]:
    words = []
    for word in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split():
        if word.endswith("s") and len(word) > 3:
            word = word[:-1]
        words.append(word)
    return set(words)


def contradiction_prompt(content: str) -> str:
    return f"Still going by “{content}”, or has that changed?"
