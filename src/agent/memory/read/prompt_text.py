"""How the answer names a default, and the `<user_memory>` block for the writer."""

from __future__ import annotations

from typing import Any


def default_label(slot: str | None, structured: dict[str, Any] | None, content: str) -> str:
    structured = structured or {}
    value = structured.get("val")
    if slot == "bedrooms" and value is not None:
        return f"{value}BR"
    if slot == "budget_max" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"≤ AED {_money(float(value))}"
    if slot == "preferred_location":
        return str(structured.get("label") or content)
    if slot == "proximity_metro":
        return "near a metro"
    if slot == "purpose" and value:
        return str(value)
    if slot == "furnished":
        return "furnished" if value else "unfurnished"
    if slot == "persona":
        return str(structured.get("persona") or content)
    return content


def disclosure_line(labels: list[str]) -> str:
    shown = " / ".join(label for label in labels if label)
    return (
        f"Using your usual {shown} filter — say 'ignore my defaults' to search wide."
    )


def render_memory_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["<user_memory>"]
    for item in items:
        provenance = item.get("provenance") or "explicit"
        confidence = item.get("confidence")
        if item.get("type") == "goal":
            tag = "goal"
        elif provenance == "inferred" and isinstance(confidence, (int, float)):
            tag = f"inferred, {float(confidence):.1f}"
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
