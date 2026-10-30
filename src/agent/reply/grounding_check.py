"""Check that every number in a finished reply comes from the lookup.

No model call. A number is allowed when the same display rounding used in
``format_figure`` matches a row, a listing fact, the listing count, a filter, a
coverage date, or the Golden Visa minimum. Anything else is one sentence.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from agent.reply.figures import _format_aed_amount, _format_grouped_number, _to_decimal
from agent.schemas.listing import GOLDEN_VISA_MIN_PRICE_AED

_AED = re.compile(
    r"\bAED\s*(\d[\d,]*(?:\.\d+)?)\s*(million|billion|m|bn|k)?\b",
    re.IGNORECASE,
)
_MONEY_WORD = re.compile(
    r"\b(\d[\d,]*(?:\.\d+)?)\s*(million|billion)\b",
    re.IGNORECASE,
)
_SQFT = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft)\b", re.IGNORECASE)
_PERCENT = re.compile(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
_COUNT = re.compile(
    r"\b(\d[\d,]*)\s*-?\s*(?:bed(?:room)?s?|baths?|listings?|properties|apartments?|"
    r"offices?|villas?|homes?|units?|sales|transactions|schools?|rows)\b",
    re.IGNORECASE,
)
_THERE_ARE = re.compile(r"\bthere\s+(?:are|is)\s+(\d[\d,]*)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SCALES = {
    "m": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
    "k": Decimal(1_000),
}
_REASON = "is not in the rows, the listings, the count, the filters, or the visa minimum."


def ungrounded_numbers(
    text: str,
    *,
    rows: list | None = None,
    listings: list | None = None,
    listing_count: int | None = None,
    filters: list | None = None,
    coverage: list | None = None,
) -> list[str]:
    """One sentence per reply number the lookup does not support. Empty when all match."""
    sources = _sources(rows or [], listings or [], listing_count, filters or [], coverage or [], text)
    flagged: list[str] = []
    for snippet, kind, stated in _claims(text or ""):
        if _matches(kind, stated, sources):
            continue
        flagged.append(f"{snippet} {_REASON}")
    return flagged


def _claims(text: str) -> list[tuple[str, str, Decimal]]:
    claimed: list[tuple[str, str, Decimal]] = []
    occupied: list[tuple[int, int]] = []

    def add(match: re.Match[str], kind: str, scale: Decimal | None = None) -> None:
        start, end = match.span(1)
        if any(left <= start < right for left, right in occupied):
            return
        number = _to_decimal(match.group(1).replace(",", ""))
        if number is None:
            return
        if scale is not None:
            number *= scale
        occupied.append((start, end))
        claimed.append((match.group(0).strip(), kind, number))

    for match in _AED.finditer(text):
        add(match, "aed", _scale(match.group(2)))
    for match in _MONEY_WORD.finditer(text):
        add(match, "aed", _scale(match.group(2)))
    for match in _SQFT.finditer(text):
        add(match, "sqft")
    for match in _PERCENT.finditer(text):
        add(match, "percent")
    for match in _YEAR.finditer(text):
        add(match, "year")
    for match in _COUNT.finditer(text):
        add(match, "count")
    for match in _THERE_ARE.finditer(text):
        add(match, "count")
    return claimed


def _scale(suffix: str | None) -> Decimal | None:
    if not suffix:
        return None
    return _SCALES.get(suffix.casefold())


def _sources(
    rows: list,
    listings: list,
    listing_count: int | None,
    filters: list,
    coverage: list,
    text: str,
) -> list[Decimal]:
    found: list[Decimal] = []
    for value in (*rows, *listings, *filters, *coverage):
        _walk(value, found)
    if rows:
        found.append(Decimal(len(rows)))
        found.extend(Decimal(count) for count in _column_counts(rows))
    if listing_count is not None:
        found.append(Decimal(listing_count))
    if "golden visa" in text.casefold():
        found.append(Decimal(GOLDEN_VISA_MIN_PRICE_AED))
    return found


def _column_counts(rows: list) -> list[int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if value not in (None, ""):
                counts[key] = counts.get(key, 0) + 1
    return list(counts.values())


def _walk(value: Any, found: list[Decimal]) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        for match in _NUMBER.finditer(value):
            number = _to_decimal(match.group(0).replace(",", ""))
            if number is not None:
                found.append(number)
        return
    number = _to_decimal(value)
    if number is not None:
        found.append(number)
        return
    if isinstance(value, dict):
        for item in value.values():
            _walk(item, found)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, found)


def _matches(kind: str, stated: Decimal, sources: list[Decimal]) -> bool:
    if kind == "aed":
        shown = _format_aed_amount(stated)
        return any(stated == source or _format_aed_amount(source) == shown for source in sources)
    if kind == "sqft":
        shown = _format_grouped_number(stated, 0)
        return any(stated == source or _format_grouped_number(source, 0) == shown for source in sources)
    if kind == "percent":
        shown = _format_grouped_number(stated, 2)
        return any(_percent_shown(source) == shown for source in sources)
    if kind == "year":
        year = int(stated)
        return any(source == source.to_integral_value() and int(source) == year for source in sources)
    shown = _format_grouped_number(stated, 0)
    return any(stated == source or _format_grouped_number(source, 0) == shown for source in sources)


def _percent_shown(source: Decimal) -> str:
    if abs(source) <= 1:
        return _format_grouped_number(source * 100, 2)
    return _format_grouped_number(source, 2)
