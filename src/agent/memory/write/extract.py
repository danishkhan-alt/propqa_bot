"""Explicit statements, episodic signatures, and behavioural inferences.

Raw SQL is never an input. A quoted preference is explicit. A click is not a memory.
"""

from __future__ import annotations

import re
from typing import Any

from agent.memory.models.records import MemoryOperation

_PREFERENCE = re.compile(
    r"\b(i prefer|i like|i want|i need|i usually|usually|always|my budget|i am an|i'm an|i am a|i'm a)\b",
    re.I,
)
_CORRECTION = re.compile(
    r"\b(actually|instead|no longer|don't care|do not care|not anymore|anymore)\b",
    re.I,
)
_BEDROOMS = re.compile(r"\b(\d+)\s*[- ]?(?:bed(?:room)?s?|br)\b", re.I)
_BUDGET = re.compile(
    r"\b(?:budget|under|below|up to|max(?:imum)?)\b[^0-9]{0,24}(\d+(?:\.\d+)?)\s*(million|m|k)?",
    re.I,
)
_METRO = re.compile(r"\b(?:near|close to|next to|walking distance to)\b.{0,24}\bmetro\b", re.I)
_FORGET_PLACE = re.compile(r"\b(don't care|do not care|no longer|not anymore)\b", re.I)


def extract_turn(job: dict[str, Any]) -> list[MemoryOperation]:
    message = str(job.get("message") or "")
    frame = job.get("query_frame") or {}
    result_meta = job.get("result_meta") or frame.get("result_meta") or {}
    ops = extract_explicit(message)
    ops.extend(extract_episodic(frame, result_meta))
    ops.extend(extract_behaviour(job.get("events") or []))
    for op in ops:
        op.source_thread_id = job.get("thread_id")
        op.source_message_id = job.get("message_id")
    return ops


def extract_explicit(message: str) -> list[MemoryOperation]:
    text = message.strip()
    if not text or not (_PREFERENCE.search(text) or _CORRECTION.search(text)):
        return []
    ops: list[MemoryOperation] = []
    if _FORGET_PLACE.search(text) and re.search(r"\b(marina|downtown|location|area|community)\b", text, re.I):
        ops.append(
            _build_memory_operation(
                "delete",
                "preference",
                "location",
                "No longer wants the saved location",
                slot="preferred_location",
                evidence=text,
            )
        )
    bedrooms = _BEDROOMS.search(text)
    if bedrooms:
        count = int(bedrooms.group(1))
        ops.append(
            _build_memory_operation(
                "update" if _CORRECTION.search(text) else "add",
                "preference",
                "property_prefs",
                f"Prefers {count}-bedroom apartments",
                slot="bedrooms",
                structured={"col": "properties.bedrooms", "op": "eq", "val": count},
                evidence=text,
            )
        )
    budget = _parse_aed_amount(_BUDGET, text)
    if budget is not None and (_PREFERENCE.search(text) or "budget" in text.lower()):
        ops.append(
            _build_memory_operation(
                "update" if _CORRECTION.search(text) else "add",
                "preference",
                "budget",
                f"Budget ≤ AED {budget:g}",
                slot="budget_max",
                structured={"col": "properties.price", "op": "lte", "val": budget, "currency": "AED"},
                evidence=text,
            )
        )
    if re.search(r"\bunfurnished\b", text, re.I):
        ops.append(_furnished_preference_operation(False, text))
    elif re.search(r"\bfurnished\b", text, re.I):
        ops.append(_furnished_preference_operation(True, text))
    if _METRO.search(text):
        ops.append(
            _build_memory_operation(
                "add",
                "preference",
                "location",
                "Prefers properties within 800m of a metro station",
                slot="proximity_metro",
                structured={"col": "properties.metro_distance_m", "op": "lte", "val": 800},
                evidence=text,
            )
        )
    if re.search(r"\b(for sale|to buy)\b", text, re.I):
        ops.append(_purpose_preference_operation("sale", text))
    elif re.search(r"\b(for rent|to rent)\b", text, re.I):
        ops.append(_purpose_preference_operation("rent", text))
    if re.search(r"\b(investor|investment|buy to let)\b", text, re.I):
        ops.append(
            _build_memory_operation(
                "add",
                "profile",
                "persona",
                "Investor",
                slot="persona",
                structured={
                    "persona": "investor",
                    "default_projection": ["roi", "rental_yield", "price_per_sqft"],
                },
                importance=0.75,
                evidence=text,
            )
        )
        ops.append(
            _build_memory_operation(
                "add",
                "goal",
                "goal",
                "Currently searching for an investment property",
                slot="active_goal",
                structured={"type": "investment_search"},
                importance=0.8,
                ttl_days=45,
                evidence=text,
            )
        )
    if re.search(r"\bbalcon", text, re.I):
        ops.append(
            _build_memory_operation(
                "add",
                "preference",
                "property_prefs",
                "Likes balconies",
                importance=0.6,
                evidence=text,
            )
        )
    if re.search(r"\b(this week|traveling|travelling|on holiday|on vacation)\b", text, re.I):
        ops.append(
            _build_memory_operation(
                "add",
                "ephemeral",
                "travel",
                text[:180],
                importance=0.45,
                ttl_days=7,
                evidence=text,
            )
        )
    return ops


def extract_episodic(frame: dict[str, Any], result_meta: dict[str, Any]) -> list[MemoryOperation]:
    predicates = frame.get("predicates") or {}
    domain = frame.get("domain") or ""
    if not predicates and not domain:
        return []
    kept_meta = {
        key: result_meta.get(key)
        for key in ("row_count", "median_price")
        if result_meta.get(key) is not None
    }
    signature = {
        "domain": domain,
        "intent": frame.get("intent") or "",
        "predicates": predicates,
        "result_meta": kept_meta,
    }
    return [
        _build_memory_operation(
            "add",
            "episodic",
            _cluster_for(domain, predicates),
            _episodic_sentence(domain, predicates, kept_meta),
            structured=signature,
            provenance="system",
            confidence=0.7,
            importance=0.45,
        )
    ]


def extract_behaviour(events: list[dict[str, Any]]) -> list[MemoryOperation]:
    ops: list[MemoryOperation] = []
    for event in events:
        kind = str(event.get("type") or "").lower()
        if kind not in {"save", "filter"}:
            continue
        if event.get("bedrooms") is not None:
            count = int(event["bedrooms"])
            ops.append(
                _build_memory_operation(
                    "add",
                    "preference",
                    "property_prefs",
                    f"Often looks at {count}-bedroom homes",
                    slot="bedrooms",
                    structured={"col": "properties.bedrooms", "op": "eq", "val": count},
                    provenance="inferred",
                    confidence=0.55,
                    importance=0.5,
                    evidence=f"{kind} bedrooms={count}",
                )
            )
        if event.get("budget_max") is not None:
            amount = float(event["budget_max"])
            ops.append(
                _build_memory_operation(
                    "add",
                    "preference",
                    "budget",
                    f"Often filters at or below AED {amount:g}",
                    slot="budget_max",
                    structured={"col": "properties.price", "op": "lte", "val": amount, "currency": "AED"},
                    provenance="inferred",
                    confidence=0.55,
                    importance=0.5,
                    evidence=f"{kind} budget",
                )
            )
    return ops


def _build_memory_operation(
    op: str,
    memory_type: str,
    cluster: str,
    content: str,
    *,
    slot: str | None = None,
    structured: dict | None = None,
    provenance: str = "explicit",
    confidence: float | None = None,
    importance: float = 0.7,
    ttl_days: int | None = None,
    evidence: str = "",
) -> MemoryOperation:
    if confidence is None:
        confidence = 0.9 if provenance == "explicit" else 0.55
    return MemoryOperation(
        op=op,
        type=memory_type,
        cluster=cluster,
        slot=slot,
        content=content,
        structured=structured,
        provenance=provenance,
        confidence=confidence,
        importance=importance,
        ttl_days=ttl_days,
        evidence=evidence[:500],
    )


def _furnished_preference_operation(value: bool, evidence: str) -> MemoryOperation:
    word = "furnished" if value else "unfurnished"
    return _build_memory_operation(
        "add",
        "preference",
        "property_prefs",
        f"Prefers {word} homes",
        slot="furnished",
        structured={"col": "properties.is_furnished", "op": "eq", "val": value},
        evidence=evidence,
    )


def _purpose_preference_operation(value: str, evidence: str) -> MemoryOperation:
    return _build_memory_operation(
        "add",
        "preference",
        "property_prefs",
        f"Prefers properties for {value}",
        slot="purpose",
        structured={"col": "properties.purpose", "op": "eq", "val": value},
        evidence=evidence,
    )


def _parse_aed_amount(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit in {"million", "m"}:
        return number * 1_000_000
    if unit == "k":
        return number * 1_000
    return number


def _cluster_for(domain: str, predicates: dict) -> str:
    if "price" in predicates or domain in {"market_intel"}:
        return "budget"
    if "location_id_v2" in predicates or domain in {"location_intel", "rta_intel"}:
        return "location"
    return "property_prefs"


def _episodic_sentence(domain: str, predicates: dict, meta: dict) -> str:
    parts = [f"Searched {(domain or 'listings').replace('_', ' ')}"]
    bedrooms = predicates.get("bedrooms")
    if isinstance(bedrooms, dict) and bedrooms.get("eq") is not None:
        parts.append(f"{bedrooms['eq']} bedrooms")
    price = predicates.get("price")
    if isinstance(price, dict) and price.get("lte") is not None:
        parts.append(f"budget {price['lte']}")
    if meta.get("row_count") is not None:
        parts.append(f"{meta['row_count']} rows")
    return ", ".join(parts)
