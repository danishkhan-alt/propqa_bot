"""Buyer preferences mirrored into the shared cache."""

from __future__ import annotations

from common.cache import get_cache
from common.session.sidebar_sessions import SESSION_TTL_SECONDS


def load(user_id: str) -> dict | None:
    stored = get_cache().get(_key(user_id), None)
    if not isinstance(stored, dict):
        return None
    return stored


def merge(user_id: str, updates: dict) -> dict:
    current = load(user_id)
    merged = dict(current) if current is not None else {}
    merged.update(updates)
    get_cache().set(_key(user_id), merged, ttl=SESSION_TTL_SECONDS)
    return merged


def clear(user_id: str) -> None:
    get_cache().delete(_key(user_id))


def _key(user_id: str) -> str:
    return f"chat:preferences:{user_id}"
