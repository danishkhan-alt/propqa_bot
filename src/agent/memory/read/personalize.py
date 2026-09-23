"""Profile defaults fill gaps in the working frame. Explicit filters already there win."""

from __future__ import annotations

from typing import Any

from agent.memory.models.column_map import (
    FILTER_COLUMNS,
    PROJECTION_DOMAINS,
    columns_for_domains,
    gate_column_for_cluster,
)
from agent.enums.memory import MemoryType
from agent.memory.write.filters import to_filter
from agent.memory.read.prompt_text import default_label, render_memory_block
from agent.memory.models.types import clone_frame


def apply_saved_preferences(
    frame: dict[str, Any] | None,
    memories: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    domains: list[str],
    *,
    ignore: bool,
) -> tuple[dict[str, Any], list[str], str]:
    current = clone_frame(frame)
    if domains and not current.get("domain"):
        current["domain"] = domains[0]
    visible = visible_memories(memories, domains)
    block = render_memory_block(visible)
    if ignore:
        return current, [], block
    allowed = columns_for_domains(domains)
    predicates = current.setdefault("predicates", {})
    labels: list[str] = []
    slotted = [
        item
        for item in visible
        if (item.get("structured") or {}).get("col")
        and item.get("type") != MemoryType.EPISODIC
    ]
    slotted.sort(key=lambda item: float(item.get("confidence") or 0), reverse=True)
    for item in slotted:
        structured = item["structured"]
        if structured["col"] not in allowed:
            continue
        key, value = to_filter(structured)
        if key in predicates:
            continue
        predicates[key] = value
        labels.append(
            default_label(item.get("slot"), structured, str(item.get("content") or key))
        )
    for key, value in (profile or {}).get("structured", {}).items():
        if key in predicates:
            continue
        logical = FILTER_COLUMNS.get(key)
        if logical and logical not in allowed:
            continue
        predicates[key] = value
        labels.append(str(key))
    if set(domains) & PROJECTION_DOMAINS:
        projection = list(current.get("projection") or [])
        for item in visible:
            structured = item.get("structured") or {}
            for column in list(structured.get("default_projection") or []) + list(
                structured.get("add_columns") or []
            ):
                if column not in projection:
                    projection.append(column)
        current["projection"] = projection
    return current, labels, block


def visible_memories(
    memories: list[dict[str, Any]], domains: list[str]
) -> list[dict[str, Any]]:
    allowed = columns_for_domains(domains)
    if not domains:
        return list(memories)
    kept = []
    for item in memories:
        column = (item.get("structured") or {}).get("col")
        if column and column not in allowed:
            continue
        required = gate_column_for_cluster(item.get("cluster"))
        if (
            required
            and required not in allowed
            and item.get("type") != MemoryType.GOAL
        ):
            continue
        kept.append(item)
    return kept
