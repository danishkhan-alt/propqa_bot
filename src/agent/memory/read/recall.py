"""Recall active memories for this turn, then rank them."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from agent.memory.storage.cache import RECALL_TTL_SECONDS
from agent.memory.read.prompt_text import render_memory_block
from agent.memory.read.scoring import score_memory
from agent.memory.models.types import DEFAULT_CLUSTERS, utcnow

_CLUSTER_WORDS = (
    ("budget", ("budget", "aed", "million", "cheap", "cheaper", "price", "afford")),
    ("location", ("marina", "downtown", "community", "area", "near", "neighbourhood", "neighborhood")),
    ("property_prefs", ("bed", "apartment", "villa", "furnished", "balcony", "sqft", "bedroom")),
    ("persona", ("invest", "yield", "roi", "tenant", "end user", "end-user")),
    ("goal", ("looking for", "searching for", "want to buy", "want to rent")),
)


def classify_clusters(text: str) -> list[str]:
    lowered = (text or "").lower()
    found = []
    for cluster, words in _CLUSTER_WORDS:
        if any(word in lowered for word in words):
            found.append(cluster)
    return found


def recall_for_user(
    repository,
    user_id: str,
    query: str,
    *,
    store=None,
    hot=None,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or utcnow()
    empty = {"memory_context": [], "memory_block": "", "memory_question": ""}
    if not user_id or repository is None and store is None:
        return empty
    settings = repository.get_settings(user_id) if repository is not None else None
    if settings is not None and not settings.memory_enabled:
        return empty
    clusters = [cluster for cluster in classify_clusters(query) if _allowed(cluster, settings)]
    if not clusters:
        return empty
    cached = _cached(hot, user_id, clusters, query)
    if cached is not None:
        _touch(repository, [item.get("id") for item in cached if item.get("id")], moment)
        return {
            "memory_context": cached,
            "memory_block": render_memory_block(cached),
            "memory_question": _question(repository, user_id),
        }
    if store is not None:
        hits = store.search(
            ("users", user_id),
            query=query,
            filter={"status": "active", "cluster": clusters},
            limit=12,
        )
        candidates = []
        for item in hits:
            value = dict(item.value)
            value["id"] = item.key
            value["similarity"] = float(item.score or 0)
            candidates.append(value)
    else:
        pairs = repository.search(user_id, query=query, clusters=clusters, status="active", limit=12, now=moment)
        candidates = []
        for record, score in pairs:
            from agent.memory.models.types import public_record

            candidates.append(public_record(record, similarity=score))
    ranked = sorted(candidates, key=lambda item: score_memory(item, now=moment), reverse=True)[:6]
    _touch(repository, [item.get("id") for item in ranked if item.get("id")], moment)
    _store_cache(hot, user_id, clusters, query, ranked)
    return {
        "memory_context": ranked,
        "memory_block": render_memory_block(ranked),
        "memory_question": _question(repository, user_id),
    }


def _allowed(cluster: str, settings) -> bool:
    if settings is None:
        return cluster in DEFAULT_CLUSTERS
    return cluster in settings.allowed_clusters


def _cache_key(user_id: str, clusters: list[str], query: str) -> str:
    raw = ",".join(sorted(clusters)) + "|" + query.strip().lower()
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"recall:{user_id}:{digest}"


def _cached(hot, user_id: str, clusters: list[str], query: str):
    if hot is None:
        return None
    value = hot.get(_cache_key(user_id, clusters, query))
    return value if isinstance(value, list) else None


def _store_cache(hot, user_id: str, clusters: list[str], query: str, ranked: list[dict]) -> None:
    if hot is None:
        return
    hot.set(_cache_key(user_id, clusters, query), ranked, ttl=RECALL_TTL_SECONDS)


def _touch(repository, memory_ids: list[str], now: datetime) -> None:
    if repository is None:
        return
    ids = [memory_id for memory_id in memory_ids if memory_id]
    if ids:
        repository.touch(ids, now=now)


def _question(repository, user_id: str) -> str:
    if repository is None:
        return ""
    event = repository.latest_open_contradiction(user_id)
    if event is None:
        return ""
    repository.mark_event(event["id"], asked=True)
    return str(event["detail"].get("prompt") or "")
