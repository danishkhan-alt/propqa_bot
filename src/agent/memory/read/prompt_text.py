"""How the answer names a default, and the `<user_memory>` block for the writer."""

from __future__ import annotations

from typing import Any

from agent.enums.memory import MemoryProvenance, MemoryType, PreferenceSlot


def default_label(slot: str | None, structured: dict[str, Any] | None, content: str) -> str:
    structured = structured or {}
    value = structured.get("val")
    if slot == PreferenceSlot.BEDROOMS and value is not None:
        return f"{value}BR"
    if slot == PreferenceSlot.BUDGET_MAX and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"≤ AED {_money(float(value))}"
    if slot == PreferenceSlot.PREFERRED_LOCATION:
        return str(structured.get("label") or content)
    if slot == PreferenceSlot.PROXIMITY_METRO:
        return "near a metro"
    if slot == PreferenceSlot.PURPOSE and value:
        return str(value)
    if slot == PreferenceSlot.FURNISHED:
        return "furnished" if value else "unfurnished"
    if slot == PreferenceSlot.PERSONA:
        return str(structured.get("persona") or content)
    return content


def disclosure_line(labels: list[str]) -> str:
    """Describe applied filters in plain language. Do not mention defaults or memory."""
    shown = " / ".join(label for label in labels if label)
    if not shown:
        return ""
    return f"Searched for {shown}."


def render_memory_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["<user_memory>"]
    for item in items:
        provenance = item.get("provenance") or MemoryProvenance.EXPLICIT
        confidence = item.get("confidence")
        if item.get("type") == MemoryType.GOAL:
            tag = MemoryType.GOAL.value
        elif provenance == MemoryProvenance.INFERRED and isinstance(confidence, (int, float)):
            tag = f"{MemoryProvenance.INFERRED.value}, {float(confidence):.1f}"
        else:
            tag = str(provenance)
        created = str(item.get("created_at") or "")
        when = f" ({created[:10]})" if len(created) >= 10 else ""
        lines.append(f"- [{tag}] {item.get('content')}{when}")
    lines.append("</user_memory>")
    return "\n".join(lines)


def append_memory_notes(text: str, disclosure: str, question: str) -> str:
    notes = [note for note in (disclosure, question) if note and note not in text]
    if not notes:
        return text
    return text.rstrip() + "\n\n" + "\n".join(notes)


def _money(value: float) -> str:
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value / 1_000_000:.0f}M"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    return f"{value:.0f}"
