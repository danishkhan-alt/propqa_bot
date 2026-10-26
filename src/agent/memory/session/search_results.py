"""Summary of the last result set for follow-ups like "cheaper" and "the second one"."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def summarize_search_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Stats for follow-ups. No SQL text."""

    prices = sorted(
        float(row["price"])
        for row in rows
        if isinstance(row.get("price"), (int, float))
        and not isinstance(row.get("price"), bool)
    )
    ids = [_result_id(row) for row in rows]
    ids = [item for item in ids if item is not None][:50]

    def percentile(fraction: float) -> float | None:
        if not prices:
            return None
        index = int(round((len(prices) - 1) * fraction))
        return prices[index]

    summary = {
        "row_count": len(rows),
        "min_price": prices[0] if prices else None,
        "p25_price": percentile(0.25),
        "median_price": percentile(0.5),
        "max_price": prices[-1] if prices else None,
        "ids": ids,
    }
    projects = _projects(rows)
    if projects:
        summary["projects"] = projects
    return summary


_PROJECT_NAME_KEYS = ("project_name_en", "project_name")
_HANDOVER_KEYS = ("handover_date", "completion_date", "project_end_date", "expected_completion_date")
_PRICE_KEYS = ("starting_price", "starting_price_aed")
_MAX_PROJECTS = 20


def _projects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The projects a follow-up can stay on: name, handover, and starting price."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = next((row.get(key) for key in _PROJECT_NAME_KEYS if row.get(key)), None)
        if name is None:
            continue
        key = " ".join(str(name).casefold().split())
        if not key or key in seen:
            continue
        seen.add(key)
        item: dict[str, Any] = {"name": str(name).strip()}
        handover = next((row.get(key) for key in _HANDOVER_KEYS if row.get(key) not in (None, "")), None)
        if handover is not None:
            item["handover"] = handover.isoformat() if hasattr(handover, "isoformat") else str(handover)
        price = next(
            (
                row.get(column)
                for column in _PRICE_KEYS
                if isinstance(row.get(column), (int, float, Decimal)) and not isinstance(row.get(column), bool)
            ),
            None,
        )
        if price is not None:
            item["starting_price"] = float(price)
        found.append(item)
        if len(found) >= _MAX_PROJECTS:
            break
    return found


def _result_id(row: dict[str, Any]) -> Any:
    for key in ("property_id", "building_id", "id"):
        if row.get(key) is not None:
            return row[key]
    return None
