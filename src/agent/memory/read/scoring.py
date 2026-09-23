"""Retrieval score: similarity, confidence, importance, and type-specific recency."""

from __future__ import annotations

from datetime import datetime
from typing import Any

HALF_LIFE_DAYS = {
    "profile": 365,
    "preference": 90,
    "semantic": 120,
    "episodic": 30,
    "goal": 45,
    "ephemeral": 3,
}


def as_datetime(value: datetime | str | None, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=fallback.tzinfo)
        return value
    if not value:
        return fallback
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=fallback.tzinfo)
    return parsed


def score_memory(memory: dict[str, Any], *, now: datetime) -> float:
    updated = as_datetime(memory.get("updated_at"), fallback=now)
    days = max(0, (now - updated).days)
    half_life = HALF_LIFE_DAYS.get(str(memory.get("type") or "preference"), 90)
    recency = 0.5 ** (days / half_life)
    similarity = float(memory.get("similarity") or 0)
    confidence = float(memory.get("confidence") or 0)
    importance = float(memory.get("importance") or 0)
    return 0.45 * similarity + 0.25 * confidence + 0.20 * importance + 0.10 * recency
