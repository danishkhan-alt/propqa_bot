"""Predicate equality, overlap, and the FilterSpec shape used by QueryFrame."""

from __future__ import annotations

from typing import Any

from agent.memory.models.column_map import EXCLUSIVE_SLOTS


def _canon_val(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(value)
    return value


def _canonical_filter_key(structured: dict[str, Any] | None) -> tuple | None:
    if not structured:
        return None
    items = []
    for key in sorted(structured):
        if key in {"label", "currency"}:
            continue
        value = structured[key]
        items.append((key, _canon_val(value)))
    return tuple(items)


def is_same_filter(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return _canonical_filter_key(left) == _canonical_filter_key(right)


def can_merge_filters(
    slot: str | None,
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> bool:
    """Same column, compatible ops, different values. Exclusive slots never merge."""
    
    if not slot or slot in EXCLUSIVE_SLOTS or not left or not right:
        return False
    
    if left.get("col") != right.get("col") or not left.get("col"):
        return False
    
    left_op = left.get("op")
    right_op = right.get("op")
    
    if left_op in {"eq", "in"} and right_op in {"eq", "in"}:
        return _canon_val(left.get("val")) != _canon_val(right.get("val"))
    
    if left_op == right_op and left_op in {"lte", "gte"}:
        return left.get("val") != right.get("val")
    
    return False


def merge_filters(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge two structured predicates."""

    merged = dict(left)
    
    if left.get("op") in {"lte", "gte"} and left.get("op") == right.get("op"):
        values = [left.get("val"), right.get("val")]
        merged["val"] = min(values) if left["op"] == "lte" else max(values)
        return merged
    
    collected: list[Any] = []
    
    for item in (left, right):
        value = item.get("val")
        if item.get("op") == "in" and isinstance(value, list):
            collected.extend(value)
        elif value is not None:
            collected.append(value)
    
    deduped: list[Any] = []
    
    for value in collected:
        if value not in deduped:
            deduped.append(value)
    
    merged["op"] = "in"
    merged["val"] = deduped
    
    return merged


def to_filter_spec_entry(structured: dict[str, Any]) -> tuple[str, Any]:
    """Turn a slotted predicate into the FilterSpec fragment QueryFrame stores."""

    key = str(structured["col"]).split(".")[-1]
    op = structured.get("op") or "eq"
    value = structured.get("val")
    if key == "purpose" and op == "eq":
        return key, value
    return key, {op: value}
