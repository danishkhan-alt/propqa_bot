"""Summary of the last result set for follow-ups like "cheaper" and "the second one"."""

from __future__ import annotations

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

    return {
        "row_count": len(rows),
        "min_price": prices[0] if prices else None,
        "p25_price": percentile(0.25),
        "median_price": percentile(0.5),
        "max_price": prices[-1] if prices else None,
        "ids": ids,
    }


def _result_id(row: dict[str, Any]) -> Any:
    for key in ("property_id", "building_id", "id"):
        if row.get(key) is not None:
            return row[key]
    return None
