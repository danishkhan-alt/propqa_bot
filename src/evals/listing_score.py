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
    coverage: list[dict] = field(default_factory=list)
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
    unsupported_claims = claims_outside_the_sheet(
        list(unsupported_claims or []),
        facts,
        outcome.total,
        len(outcome.listing_ids),
    )
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
        "asking_price_min_aed",
        "asking_price_max_aed",
        "rent_aed",
        "rental_period",
        "area_sqft",
        "building",
        "project",
        "completion",
        "furnished",
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


_COUNT_CLAIM = re.compile(
    r"\b(?:there are|has|have)\s+(\d[\d,]*)\b"
    r"|\b(\d[\d,]*)\s+(?:active\s+)?(?:listings|properties|apartments|offices|villas|homes|units)\b",
    re.IGNORECASE,
)
_UNDER_AMOUNT = re.compile(
    r"\b(?:under|below|up to|within|less than|over|above|more than|at most|at least)\s+"
    r"(?:aed\s*)?[\d,.]+\s*(?:million|billion|m|bn|k)?\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn|k)?\b", re.IGNORECASE)
_RANGE_SCALE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s+(?:to|–|-)\s+(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn|k)\b",
    re.IGNORECASE,
)
_OFF_PLAN = re.compile(r"off[\s-]?plan", re.IGNORECASE)
_FURNISHED = re.compile(r"\bfurnished\b", re.IGNORECASE)
_READY = re.compile(r"\bready\b", re.IGNORECASE)
_SKIP_NUMBER_KEYS = frozenset(
    {
        "id",
        "title",
        "purpose",
        "completion",
        "furnished",
        "address",
        "community",
        "developer",
        "building",
        "project",
        "rental_period",
        "place_links",
        "categories",
        "amenities",
        "views",
        "text_match",
        "verified_agent",
        "matches_filters",
    }
)


_CURRENCY_BEFORE = re.compile(r"(?:AED|Dhs?\.?|USD|\$)\s*$", re.IGNORECASE)
_UNIT_AFTER = re.compile(
    r"\s*(?:%|per\s?cent\b|sq\.?\s?ft\b|sqft\b|sq\.?\s?m\b|sqm\b|m²"
    r"|[kmb]n?\b|million\b|billion\b|thousand\b|AED\b|dirhams?\b)"
    r"|[\s-]*(?:bed(?:room)?s?|b\s*/\s*r|br|bath(?:room)?s?)\b",
    re.IGNORECASE,
)


def _unitless(text: str, start: int, end: int) -> bool:
    """True when the number has no currency, magnitude, size, percent, or room marker."""
    return not (
        _CURRENCY_BEFORE.search(text[max(0, start - 6) : start]) or _UNIT_AFTER.match(text, end)
    )


def supported_as_listing_total(
    text: str,
    start: int,
    end: int,
    inventory_total: int | None,
    returned: int,
) -> bool:
    """A unitless number equal to the inventory total, in any word order.

    The page length counts only when the sentence says "N of the total".
    """
    if inventory_total is None or not _unitless(text, start, end):
        return False
    value = float(text[start:end].replace(",", ""))
    if value == inventory_total:
        return True
    total = rf"(?:{int(inventory_total)}|{int(inventory_total):,})"
    return value == returned and re.match(rf"\s+of\s+(?:the\s+)?{total}\b", text[end:]) is not None


def _inventory_totals(text: str, inventory_total: int | None, returned: int) -> set:
    """Unitless numbers the inventory-total rule already explains."""
    found: set = set()
    name_spans = [match.span() for match in _PROPER_NAME.finditer(text)]
    for match in _NUMBER.finditer(text):
        if any(start <= match.start() < end for start, end in name_spans):
            continue
        if supported_as_listing_total(text, match.start(1), match.end(1), inventory_total, returned):
            found.add(_scaled(match.group(1), match.group(2)))
    return found


def _bare_page_count(text: str, inventory_total: int | None, returned: int) -> bool:
    """A small unitless number that is not the inventory total and not "N of the total"."""
    name_spans = [match.span() for match in _PROPER_NAME.finditer(text)]
    for match in _NUMBER.finditer(text):
        if any(start <= match.start() < end for start, end in name_spans):
            continue
        start, end = match.start(1), match.end(1)
        if not _unitless(text, start, end):
            continue
        number = _scaled(match.group(1), match.group(2))
        if not isinstance(number, int) or number > 20:
            continue
        if supported_as_listing_total(text, start, end, inventory_total, returned):
            continue
        return True
    return False


def claims_outside_the_sheet(
    claims: list[str],
    facts: list[dict],
    inventory_total: int | None,
    returned: int = 0,
) -> list[str]:
    """Claims a returned page does not support.

    An inventory count is supported only when it equals ``inventory_total``. A count of the
    raw page is not the inventory when that total is missing. Completion and furnished may be
    stated when a returned listing says so. A price or size that is not on the sheet stays.
    """
    sheet_numbers = _sheet_numbers(facts)
    off_plan = any(_is_off_plan(fact.get("completion")) for fact in facts)
    ready = any(_is_ready(fact.get("completion")) for fact in facts)
    furnished = any(_is_furnished(fact.get("furnished")) for fact in facts)
    return [
        claim
        for claim in claims
        if not _sheet_supports(
            claim, sheet_numbers, inventory_total, off_plan, ready, furnished, facts, returned
        )
    ]


def _sheet_supports(
    claim: str,
    sheet_numbers: set,
    inventory_total: int | None,
    off_plan: bool,
    ready: bool,
    furnished: bool,
    facts: list[dict],
    returned: int = 0,
) -> bool:
    if _OFF_PLAN.search(claim) and not off_plan:
        return False
    if _READY.search(claim) and not ready:
        return False
    if _FURNISHED.search(claim) and not re.search(r"\bunfurnished\b", claim, re.IGNORECASE) and not furnished:
        return False
    text = _UNDER_AMOUNT.sub(" ", claim)
    numbers = _claim_numbers(text)
    comparable = _with_stated_rent(claim, facts, sheet_numbers)
    count = _count_number(claim)
    if count is not None:
        if inventory_total is None or count != int(inventory_total):
            return False
        numbers.discard(count)
    numbers -= _inventory_totals(text, inventory_total, returned)
    if _bare_page_count(text, inventory_total, returned):
        return False
    if numbers and not _covered(numbers, comparable):
        return False
    if _OFF_PLAN.search(claim) or _READY.search(claim) or (
        _FURNISHED.search(claim) and not re.search(r"\bunfurnished\b", claim, re.IGNORECASE)
    ):
        return True
    return not _places_outside_the_sheet(claim, facts)


_RENT_PERIOD = re.compile(
    r"(?:/\s*|per\s+)(month|week|year)\b|\b(monthly|weekly|yearly|annually|annual)\b",
    re.IGNORECASE,
)
_RENT_TO_YEAR = {"yearly": 1, "monthly": 12, "weekly": 52}


def _covered(numbers: set, sheet_numbers: set) -> bool:
    return all(_on_sheet(number, sheet_numbers) for number in numbers)


def _with_stated_rent(claim: str, facts: list[dict], sheet_numbers: set) -> set:
    """The sheet numbers plus the stored rent written in the period the claim uses."""
    stated = _stated_rent_period(claim)
    if stated is None:
        return sheet_numbers
    converted = set(sheet_numbers)
    for fact in facts:
        rent = _number_value(fact.get("rent_aed"))
        if rent is None:
            continue
        stored = _stored_rent_period(fact.get("rental_period"))
        if stored == stated:
            continue
        yearly = rent * _RENT_TO_YEAR[stored]
        amount = yearly / _RENT_TO_YEAR[stated]
        converted.add(int(amount) if float(amount).is_integer() else amount)
    return converted


def _stated_rent_period(claim: str) -> str | None:
    match = _RENT_PERIOD.search(claim)
    if match is None:
        return None
    return _period_name(match.group(1) or match.group(2))


def _stored_rent_period(value: Any) -> str:
    return _period_name(value) or "yearly"


def _period_name(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text.startswith("month"):
        return "monthly"
    if text.startswith("week"):
        return "weekly"
    if text.startswith("year") or text.startswith("annual"):
        return "yearly"
    return None


def _on_sheet(number, sheet_numbers: set) -> bool:
    """Exact, within 2 percent, or the same value rounded to a nearby step."""
    for sheet in sheet_numbers:
        if number == sheet:
            return True
        if isinstance(number, bool) or isinstance(sheet, bool):
            continue
        if not isinstance(number, (int, float)) or not isinstance(sheet, (int, float)):
            continue
        if abs(number - sheet) <= 0.02 * max(abs(sheet), 1):
            return True
        if float(number).is_integer():
            stated = int(number)
            for step in (10, 100, 1_000, 10_000, 100_000):
                if step > abs(sheet) / 2:
                    break
                if int(round(sheet / step) * step) == stated:
                    return True
    return False


_SKIP_NAMES = frozenset(
    {"the", "these", "there", "this", "that", "they", "aed", "from", "with", "and", "for"}
)
_PROPER_NAME = re.compile(
    r"\b([A-Z][A-Za-z'’]+(?:\s+\d+)?(?:\s+[A-Z][A-Za-z'’]+)+(?:\s+\d+)?)\b"
)


def _places_outside_the_sheet(claim: str, facts: list[dict]) -> bool:
    """A capitalised place in the claim that no returned listing names."""
    sheet = _sheet_text(facts)
    for match in _PROPER_NAME.finditer(claim):
        name = match.group(1)
        if name.casefold() in _SKIP_NAMES:
            continue
        if not _name_on_sheet(name, sheet, claim):
            return True
    return False


def _name_on_sheet(name: str, sheet: str, claim: str) -> bool:
    """The building name, or that name with a trailing bedroom count taken off."""
    if name.casefold() in sheet:
        return True
    bedroom = re.match(r"^(?P<body>.+?)\s+(?P<beds>\d{1,2})$", name)
    if bedroom is None or int(bedroom.group("beds")) > 20:
        return False
    body = bedroom.group("body")
    if body.casefold() not in sheet:
        return False
    return re.search(
        rf"\b{re.escape(body)}\s+{bedroom.group('beds')}\s*-?\s*(?:bed|b\s*/\s*r)",
        claim,
        re.IGNORECASE,
    ) is not None


def _sheet_text(facts: list[dict]) -> str:
    parts: list[str] = []
    for fact in facts:
        for key in ("title", "building", "project", "community", "address", "developer", "purpose", "completion"):
            if fact.get(key):
                parts.append(str(fact[key]))
        for key in ("categories", "amenities", "views"):
            parts.extend(str(item) for item in fact.get(key) or [])
    return " ".join(parts).casefold()


def _count_number(claim: str) -> int | None:
    match = _COUNT_CLAIM.search(claim)
    if match is None:
        return None
    raw = (match.group(1) or match.group(2)).replace(",", "")
    return int(raw)


def _claim_numbers(text: str) -> set:
    found: set = set()
    name_spans = [match.span() for match in _PROPER_NAME.finditer(text)]
    shared: list[tuple[int, int]] = []
    for match in _RANGE_SCALE.finditer(text):
        if any(start <= match.start() < end for start, end in name_spans):
            continue
        shared.append(match.span())
        for group in (1, 2):
            _keep_claim_number(found, _scaled(match.group(group), match.group(3)))
    for match in _NUMBER.finditer(text):
        if any(start <= match.start() < end for start, end in (*name_spans, *shared)):
            continue
        _keep_claim_number(found, _scaled(match.group(1), match.group(2)))
    return found


def _keep_claim_number(found: set, number) -> None:
    if isinstance(number, int) and number <= 20:
        return
    found.add(number)


def _scaled(raw: str, suffix: str | None):
    number = float(raw.replace(",", "")) if "." in raw else int(raw.replace(",", ""))
    scale = (suffix or "").lower()
    if scale in {"m", "million"}:
        number *= 1_000_000
    elif scale in {"bn", "billion"}:
        number *= 1_000_000_000
    elif scale == "k":
        number *= 1_000
    if isinstance(number, float) and number.is_integer():
        return int(number)
    return number


def _sheet_numbers(facts: list[dict]) -> set:
    found: set = set()
    for fact in facts:
        for key, value in fact.items():
            if key in _SKIP_NUMBER_KEYS:
                continue
            number = _number_value(value)
            if number is not None:
                found.add(number)
            if isinstance(value, dict):
                nested = _number_value(value.get("amount"))
                if nested is not None:
                    found.add(nested)
    return found


def _number_value(value: Any):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    return None


def _is_off_plan(value: Any) -> bool:
    text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    return text in {"off plan", "offplan"}


def _is_ready(value: Any) -> bool:
    text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    return text in {"ready", "completed", "complete"}


def _is_furnished(value: Any) -> bool:
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    if text in {"", "0", "no", "false", "unfurnished", "none"}:
        return False
    if text in {"yes", "y", "true", "furnished", "semi-furnished", "semi furnished"}:
        return True
    return "furnish" in text
