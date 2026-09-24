"""Fixed clarifying questions. The model does not invent new question types."""

from __future__ import annotations

import re
from typing import Any

_PROFILE_KEYS = ("family_size", "purpose", "budget_range", "timeline")

_ADVISORY = (
    "where should i",
    "where do i buy",
    "where to buy",
    "should i buy",
    "should i go",
    "good investment",
    "which area",
    "which community",
    "which neighbourhood",
    "which neighborhood",
    "recommend",
    "best area",
    "best place",
)

_FACTUAL = (
    "what is the",
    "what's the",
    "whats the",
    "how many",
    "how much",
    "average ",
    "yield in",
    "price of",
    "service charge",
)

PURPOSE = {
    "id": "purpose",
    "label": "Living in it, investing, or both?",
    "type": "single_select",
    "options": [
        {"id": "live", "label": "Live in it"},
        {"id": "invest", "label": "Invest"},
        {"id": "both", "label": "Both"},
    ],
}

BUDGET = {
    "id": "budget_range",
    "label": "Roughly what budget, in AED?",
    "type": "single_select",
    "options": [
        {"id": "under_1m", "label": "Under 1M"},
        {"id": "1m_2m", "label": "1M–2M"},
        {"id": "2m_4m", "label": "2M–4M"},
        {"id": "4m_plus", "label": "4M+"},
    ],
}

TIMELINE = {
    "id": "timeline",
    "label": "Ready to move, or willing to wait on off-plan?",
    "type": "single_select",
    "options": [
        {"id": "ready", "label": "Ready to move"},
        {"id": "off_plan", "label": "Can wait on off-plan"},
    ],
}

_QUESTIONS = (PURPOSE, BUDGET, TIMELINE)
_BUDGET_IDS = {option["id"] for option in BUDGET["options"]}
_PURPOSE_IDS = {option["id"] for option in PURPOSE["options"]}
_TIMELINE_IDS = {option["id"] for option in TIMELINE["options"]}


def is_advisory(message: str) -> bool:
    text = message.lower()
    advisory = any(phrase in text for phrase in _ADVISORY)
    factual = any(phrase in text for phrase in _FACTUAL)
    if factual and not advisory:
        return False
    return advisory


def merge_profile(existing: dict[str, Any] | None, incoming: dict[str, Any] | None, message: str) -> dict[str, Any]:
    """Keep known answers, then apply this turn's explicit facts."""
    profile: dict[str, Any] = {}
    for source in (existing or {}, incoming or {}):
        for key in _PROFILE_KEYS:
            value = source.get(key)
            if value not in (None, ""):
                profile[key] = value
    inferred = _infer(message)
    for key, value in inferred.items():
        if profile.get(key) in (None, ""):
            profile[key] = value
    return {key: profile[key] for key in _PROFILE_KEYS if key in profile}


def clarifying_questions(message: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """At most two, and only for an advisory question with a missing fact."""
    if not is_advisory(message):
        return []
    missing = []
    if profile.get("purpose") not in _PURPOSE_IDS:
        missing.append(PURPOSE)
    if profile.get("budget_range") not in _BUDGET_IDS:
        missing.append(BUDGET)
    if len(missing) < 2 and profile.get("timeline") not in _TIMELINE_IDS:
        missing.append(TIMELINE)
    return missing[:2]


_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}


def _infer(message: str) -> dict[str, Any]:
    text = message.lower()
    found: dict[str, Any] = {}
    family = re.search(r"family of (\d+|one|two|three|four|five|six|seven|eight)", text)
    if family:
        token = family.group(1)
        found["family_size"] = int(token) if token.isdigit() else _NUMBERS[token]
    if re.search(r"\b(invest(?:ment|ing)?|rental income)\b", text):
        found["purpose"] = "invest"
    elif re.search(r"\b(live in|living in|to live|end[- ]user|relocating)\b", text):
        found["purpose"] = "live"
    elif re.search(r"\bboth\b", text) and is_advisory(message):
        found["purpose"] = "both"
    budget = _budget(text)
    if budget:
        found["budget_range"] = budget
    if "off-plan" in text or "off plan" in text:
        found["timeline"] = "off_plan"
    elif "ready to move" in text or "ready-to-move" in text:
        found["timeline"] = "ready"
    return found


def _budget(text: str) -> str | None:
    if "under 1" in text or "below 1" in text:
        return "under_1m"
    if "4m+" in text or "over 4" in text or "above 4" in text:
        return "4m_plus"
    if "2m" in text and "4m" in text:
        return "2m_4m"
    if "1m" in text and "2m" in text:
        return "1m_2m"
    return None
