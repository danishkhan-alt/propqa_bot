"""Nightly expiry, decay, semantic inference, and the profile summary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from agent.memory.write.filters import to_filter
from agent.memory.storage.repository import new_id
from agent.memory.session.bootstrap import invalidate
from agent.memory.models.types import MemoryRecord, utcnow

_PREDICATE_SLOT = {
    "bedrooms": "bedrooms",
    "price": "budget_max",
    "location_id_v2": "preferred_location",
    "purpose": "purpose",
    "is_furnished": "furnished",
    "metro_distance_m": "proximity_metro",
}


def consolidate_all(repository, *, now: datetime | None = None, summarize=None) -> None:
    moment = now or utcnow()
    for user_id in repository.list_user_ids():
        consolidate_user(repository, user_id, now=moment, summarize=summarize)


def consolidate_user(repository, user_id: str, *, now: datetime | None = None, summarize=None) -> None:
    moment = now or utcnow()
    settings = repository.get_settings(user_id)
    with repository.transaction():
        _expire(repository, user_id, moment)
        _decay(repository, user_id, moment)
        _infer(repository, user_id, moment)
        _summarise(repository, user_id, moment, summarize)
        _retain(repository, user_id, settings, moment)
    invalidate(user_id)


def _expire(repository, user_id: str, now: datetime) -> None:
    for row in repository.list_all(user_id):
        if row.status != "active" or row.expires_at is None or row.expires_at > now:
            continue
        row.status = "expired"
        row.updated_at = now
        repository.update(row)
        repository.add_event(user_id, row.id, "expired", "worker", {}, now)


def _decay(repository, user_id: str, now: datetime) -> None:
    for row in repository.list_active(user_id, now=now):
        if row.provenance != "inferred":
            continue
        anchor = row.last_accessed_at or row.updated_at
        if (now - anchor).days < 7:
            continue
        if repository.decayed_recently(row.id, since=now - timedelta(days=6)):
            continue
        row.confidence = row.confidence * 0.97
        if row.confidence < 0.3:
            row.status = "expired"
            row.updated_at = now
            repository.update(row)
            repository.add_event(user_id, row.id, "expired", "worker", {"decay": True}, now)
        else:
            repository.update(row)
            repository.add_event(user_id, row.id, "updated", "worker", {"decay": True}, now)


def _infer(repository, user_id: str, now: datetime) -> None:
    groups: dict[str, list[MemoryRecord]] = {}
    for row in repository.list_active(user_id, now=now):
        if row.type != "episodic":
            continue
        key = _predicate_key(row.structured)
        if not key:
            continue
        groups.setdefault(key, []).append(row)
    for key, rows in groups.items():
        if len(rows) < 3:
            continue
        predicates = (rows[0].structured or {}).get("predicates") or {}
        if _explicit_covers(repository, user_id, predicates):
            continue
        if _semantic_exists(repository, user_id, key):
            continue
        structured = _semantic_structured(predicates)
        record = MemoryRecord(
            id=new_id(),
            user_id=user_id,
            type="semantic",
            cluster=rows[0].cluster,
            slot=_single_slot(predicates),
            content=_semantic_sentence(predicates),
            structured={"predicates": predicates, "source": "episodic", **structured},
            confidence=0.6,
            importance=0.55,
            provenance="inferred",
            created_at=now,
            updated_at=now,
            valid_from=now,
        )
        if record.slot and repository.get_active_slot(user_id, record.slot):
            record.slot = None
        repository.insert(record)
        repository.add_event(user_id, record.id, "created", "worker", {"inferred_from": key}, now)


def _summarise(repository, user_id: str, now: datetime, summarize) -> None:
    active = repository.list_active(user_id, now=now)
    profile = repository.get_profile(user_id)
    stale = profile is None or (now - profile["updated_at"]).days >= 7
    if not active or (len(active) <= 60 and not stale):
        return
    if summarize is not None:
        summary, structured = summarize(active)
    else:
        text = " ".join(row.content for row in active if row.type != "episodic")
        summary = clip_words(text, 150) or "No saved preferences yet."
        structured = _profile_structured(active)
    repository.save_profile(user_id, summary, structured, now=now)
    repository.add_event(user_id, None, "consolidated", "worker", {"items": len(active)}, now)
    _retire_episodic(repository, user_id, active, now)


def _retain(repository, user_id: str, settings, now: datetime) -> None:
    if settings.retention_days:
        cutoff = now - timedelta(days=int(settings.retention_days))
        for row in repository.list_all(user_id):
            if row.status == "active" and row.created_at < cutoff:
                row.status = "expired"
                row.updated_at = now
                repository.update(row)
                repository.add_event(user_id, row.id, "expired", "worker", {"retention": True}, now)
    repository.hard_delete_status(status="deleted", older_than=now - timedelta(days=30))


def _predicate_key(structured: dict[str, Any] | None) -> str:
    predicates = (structured or {}).get("predicates") or {}
    if not predicates:
        return ""
    return json.dumps(predicates, sort_keys=True, default=str)


def _explicit_covers(repository, user_id: str, predicates: dict) -> bool:
    for name in predicates:
        slot = _PREDICATE_SLOT.get(name)
        if not slot:
            continue
        existing = repository.get_active_slot(user_id, slot)
        if existing is not None and existing.provenance == "explicit":
            return True
    return False


def _semantic_exists(repository, user_id: str, key: str) -> bool:
    for row in repository.list_active(user_id):
        if row.type == "semantic" and _predicate_key(row.structured) == key:
            return True
        if row.type == "semantic" and json.dumps((row.structured or {}).get("predicates") or {}, sort_keys=True, default=str) == key:
            return True
    return False


def _single_slot(predicates: dict) -> str | None:
    if len(predicates) != 1:
        return None
    return _PREDICATE_SLOT.get(next(iter(predicates)))


def _semantic_structured(predicates: dict) -> dict[str, Any]:
    if len(predicates) != 1:
        return {}
    name, value = next(iter(predicates.items()))
    column = {
        "bedrooms": "properties.bedrooms",
        "price": "properties.price",
        "location_id_v2": "properties.location_id_v2",
        "purpose": "properties.purpose",
    }.get(name)
    if column is None or not isinstance(value, dict):
        return {}
    op, raw = next(iter(value.items()))
    return {"col": column, "op": op, "val": raw}


def _semantic_sentence(predicates: dict) -> str:
    bits = []
    bedrooms = predicates.get("bedrooms")
    if isinstance(bedrooms, dict) and bedrooms.get("eq") is not None:
        bits.append(f"{bedrooms['eq']} bedrooms")
    price = predicates.get("price")
    if isinstance(price, dict) and price.get("lte") is not None:
        bits.append(f"a budget at or below {price['lte']}")
    if not bits:
        bits.append("the same kind of search")
    return "Generally prefers " + " and ".join(bits)


def _profile_structured(rows: list[MemoryRecord]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row.confidence, reverse=True)
    structured: dict[str, Any] = {}
    for row in ordered:
        body = row.structured or {}
        if "col" not in body or row.type == "episodic":
            continue
        try:
            key, value = to_filter(body)
        except (KeyError, TypeError):
            continue
        if key not in structured:
            structured[key] = value
    return structured


def _retire_episodic(repository, user_id: str, rows: list[MemoryRecord], now: datetime) -> None:
    semantic_keys = {
        json.dumps((row.structured or {}).get("predicates") or {}, sort_keys=True, default=str)
        for row in rows
        if row.type == "semantic"
    }
    semantic_keys.discard("")
    grouped: dict[str, list[MemoryRecord]] = {}
    for row in rows:
        if row.type != "episodic":
            continue
        key = _predicate_key(row.structured)
        if key in semantic_keys:
            grouped.setdefault(key, []).append(row)
    for group in grouped.values():
        group.sort(key=lambda row: row.created_at, reverse=True)
        for row in group[1:]:
            row.status = "superseded"
            row.updated_at = now
            repository.update(row)
            repository.add_event(user_id, row.id, "superseded", "worker", {"redundant": True}, now)


def clip_words(text: str, limit: int = 150) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return (text or "").strip()
    return " ".join(words[:limit])
