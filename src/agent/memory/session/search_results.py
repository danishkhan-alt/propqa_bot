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
    ids = [row["id"] for row in rows if row.get("id") is not None][:50]

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
