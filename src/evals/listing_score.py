"""Score a property-search turn against an independent truth set and a fact sheet.

The truth set and the fact sheet are loaded by the runner. This module only decides
whether the returned ids, the notes, and the reply are justified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from common.schemas.pagination import DEFAULT_PER_PAGE


@dataclass
class TurnOutcome:
    """What the last turn of a case produced."""

    sql: str = ""
    status: str = ""
    rows: list[dict] = field(default_factory=list)
    listing_ids: list[str] = field(default_factory=list)
    total: int | None = None
    notes: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    names: list[dict] = field(default_factory=list)
    route: dict = field(default_factory=dict)
    reply: str = ""
    seconds: float = 0.0
    error: str = ""


def score_listing_result(
    expected: dict,
    outcome: TurnOutcome,
    truth: set[str],
    *,
    relaxed: bool,
    facts: list[dict],
    unsupported_claims: list[str],
) -> tuple[bool, str]:
    """Whether the page, each returned listing, and the reply match this case."""
    returned = set(outcome.listing_ids)
    wrong = sorted(returned - truth)
    page_size = outcome.route.get("limit") or DEFAULT_PER_PAGE
    expected_on_page = min(len(truth), page_size)
    total_ok = outcome.total is None or outcome.total == len(truth)
    note_ok = not relaxed or bool(outcome.notes)
    broke = _rows_that_break_filters(outcome.listing_ids, facts)
    reply_problems = _reply_problems(expected, outcome, relaxed=relaxed)
    passed = (
        not wrong
        and len(returned) == expected_on_page
        and total_ok
        and note_ok
        and not broke
        and not reply_problems
        and not unsupported_claims
    )
    detail = (
        f"truth={len(truth)}{' (relaxed)' if relaxed else ''} returned={len(returned)} "
        f"total={outcome.total} wrong={len(wrong)}"
    )
    if wrong:
        detail += f" wrong_ids={','.join(wrong[:5])}"
    if not total_ok:
        detail += " total_mismatch"
    if relaxed and not outcome.notes:
        detail += " missing relaxation note"
    if broke:
        detail += f" broke_filters={','.join(broke[:5])}"
    if reply_problems:
        detail += f" reply={'; '.join(reply_problems)}"
    if unsupported_claims:
        detail += f" unsupported={'; '.join(unsupported_claims[:3])}"
    return passed, detail


def _rows_that_break_filters(listing_ids: list[str], facts: list[dict]) -> list[str]:
    """Returned ids whose fact sheet does not satisfy the case filters."""
    by_id = {str(fact.get("id")): fact for fact in facts}
    broke: list[str] = []
    for listing_id in listing_ids:
        fact = by_id.get(str(listing_id))
        if fact is None or fact.get("matches_filters") is False:
            broke.append(str(listing_id))
    return broke


def _reply_problems(expected: dict, outcome: TurnOutcome, *, relaxed: bool) -> list[str]:
    reply = outcome.reply or ""
    folded = reply.lower()
    problems: list[str] = []
    missing = [phrase for phrase in expected.get("reply_contains") or [] if phrase.lower() not in folded]
    if missing:
        problems.append("missing " + ", ".join(missing))
    if relaxed:
        missing_relaxed = [
            phrase for phrase in expected.get("reply_contains_when_relaxed") or [] if phrase.lower() not in folded
        ]
        if missing_relaxed:
            problems.append("missing after relax " + ", ".join(missing_relaxed))
    present = [phrase for phrase in expected.get("reply_omits") or [] if phrase.lower() in folded]
    if present:
        problems.append("should omit " + ", ".join(present))
    if expected.get("count_in_reply") and not _reply_has_count(outcome.total, reply):
        problems.append(f"count {outcome.total} not in reply")
    return problems


def _reply_has_count(total: int | None, reply: str) -> bool:
    if total is None:
        return False
    compact = reply.replace(",", "")
    return re.search(rf"(?<!\d){int(total)}(?!\d)", compact) is not None


def judge_fields(fact: dict[str, Any]) -> dict[str, Any]:
    """The fact-sheet columns the reply judge is allowed to read."""
    kept = (
        "id",
        "title",
        "purpose",
        "rooms",
        "asking_price_aed",
        "area_sqft",
        "categories",
        "amenities",
        "views",
        "place_links",
        "community",
        "address",
        "developer",
        "text_match",
        "verified_agent",
    )
    return {key: fact[key] for key in kept if key in fact and fact[key] not in (None, "", [])}
