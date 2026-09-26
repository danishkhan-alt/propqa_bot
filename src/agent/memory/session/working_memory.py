"""Per-chat working memory and the per-user profile, read and written through the memory cache."""

from __future__ import annotations

from agent.memory.models.records import clone_frame
from agent.memory.session.backends import get_memory_cache, get_repository
from agent.memory.storage.cache import PROFILE_TTL_SECONDS, WORKING_MEMORY_TTL_SECONDS


def load_working_memory(thread_id: str) -> dict | None:
    memory_cache = get_memory_cache()
    if memory_cache is None or not thread_id:
        return None
    value = memory_cache.get(f"wm:{thread_id}")
    return value if isinstance(value, dict) else None


def save_working_memory(thread_id: str, frame, goal, ignore_defaults: bool) -> None:
    memory_cache = get_memory_cache()
    if memory_cache is None or not thread_id:
        return

    stored = clone_frame(frame) if frame else None
    if stored is not None:
        stored["sql"] = (frame or {}).get("sql") or ""
    memory_cache.set(
        f"wm:{thread_id}",
        {"query_frame": stored, "goal": goal, "ignore_defaults": bool(ignore_defaults)},
        ttl=WORKING_MEMORY_TTL_SECONDS,
    )


def load_cached_profile(user_id: str) -> dict:
    """The user's profile from the memory cache, else from the repository (and cache it)."""
    if not user_id:
        return {}
    memory_cache = get_memory_cache()
    if memory_cache is not None:
        cached = memory_cache.get(f"profile:{user_id}")
        if isinstance(cached, dict):
            return cached
    repository = get_repository()
    if repository is None:
        return {}
    profile = repository.get_profile(user_id) or {}
    if not profile:
        return {}
    stored = {
        "summary": profile.get("summary") or "",
        "structured": profile.get("structured") or {},
        "version": profile.get("version") or 1,
    }
    if memory_cache is not None:
        memory_cache.set(f"profile:{user_id}", stored, ttl=PROFILE_TTL_SECONDS)
    return stored


def invalidate_user_memory_cache(user_id: str) -> None:
    """Drop the user's cached profile and recall results after their memories change."""
    memory_cache = get_memory_cache()
    if memory_cache is None or not user_id:
        return
    memory_cache.delete(f"profile:{user_id}")
    memory_cache.delete_prefix(f"recall:{user_id}:")
