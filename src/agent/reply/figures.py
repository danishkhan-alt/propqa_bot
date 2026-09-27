"""Reply blocks laid out from the lookup rows and map pins, and the one-block limit per reply.

The answer model only names columns, labels, and units. Every value shown is copied
from the rows here, so a figure on screen always matches the data.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from agent.reply.place_map import build_place_map
from agent.schemas.reply import (
    Explainer,
    FigureColumn,
    FigureSeries,
    FigureSpec,
    StructuredReply,
)

MAX_FIGURE_ROWS = 8
MAX_LINE_POINTS = 36
MAX_LINE_SERIES = 3
MIN_LINE_POINTS = 3
# A column repeating one of these in every row is context, such as the period, not a finding.
_CAPTION_UNITS = frozenset({"text", "year"})
_CHANGE_COLUMN = re.compile(r"change|growth", re.IGNORECASE)


def build_figures(
    spec: FigureSpec | None, rows: list[dict[str, Any]], columns: list[str]
) -> dict[str, Any] | None:
    """The UI payload for `spec`, or None when the rows cannot fill it."""
    if spec is None or spec.layout == "none" or not rows:
        return None
    known = set(columns) or set(rows[0])
    figures = _dedupe_by_column(
        _mark_change_unit(item)
        for item in spec.columns
        if item.column in known and item.column != spec.label_column
    )
    if not figures:
        return None
    label_column = spec.label_column if spec.label_column in known else ""
    if spec.series_column:
        if spec.series_column not in known or not label_column or not spec.series:
            return None
        rows, figures = _pivot(
            rows, label_column, spec.series_column, figures[0], spec.series
        )
        if not rows:
            return None
    if spec.layout == "stats":
        return _build_stats_layout(figures, rows)
    if spec.layout == "table":
        return _build_table_layout(figures, label_column, spec.label_title, rows)
    if spec.layout == "bar":
        return _build_bar_layout(figures[0], label_column, rows)
    if spec.layout == "line":
        return _build_line_layout(figures, label_column, rows)
    return None


def _dedupe_by_column(items) -> list[FigureColumn]:
    """Each data column once. Two headers over the same values would show one figure as two."""
    seen: set[str] = set()
    kept: list[FigureColumn] = []
    for item in items:
        if item.column not in seen:
            seen.add(item.column)
            kept.append(item)
    return kept


def _pivot(
    rows: list[dict[str, Any]],
    label_column: str,
    series_column: str,
    figure: FigureColumn,
    series: list[FigureSeries],
) -> tuple[list[dict[str, Any]], list[FigureColumn]]:
    """Rows of (label, series value, figure) as one row per label with a column per series value.

    Labels keep the order the rows gave them. The first row for a label and value wins.
    """
    wanted = {_normalize_text(item.value): f"series_{index}" for index, item in enumerate(series)}
    pivoted: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = _normalize_text(row.get(label_column))
        key = wanted.get(_normalize_text(row.get(series_column)))
        if not label or key is None:
            continue
        target = pivoted.setdefault(label, {label_column: row.get(label_column)})
        target.setdefault(key, row.get(figure.column))
    figures = [
        FigureColumn(column=f"series_{index}", label=item.label, unit=figure.unit)
        for index, item in enumerate(series)
        if any(f"series_{index}" in row for row in pivoted.values())
    ]
    return list(pivoted.values()), figures


def _mark_change_unit(item: FigureColumn) -> FigureColumn:
    """A percent column named as a change or growth is a rise or fall, so it shows its direction.

    Lookups name such columns that way (yearly_change_pct), so this does not rest on the
    answer model picking the right unit.
    """
    if item.unit == "percent" and _CHANGE_COLUMN.search(item.column):
        return item.model_copy(update={"unit": "change"})
    return item


def build_explainer(explainer: Explainer | None) -> dict[str, Any] | None:
    if explainer is None or explainer.kind == "none":
        return None
    if not explainer.points and not (
        explainer.kind == "pros_cons" and explainer.cautions
    ):
        return None
    payload = explainer.model_dump()
    if explainer.kind != "pros_cons":
        payload["cautions"] = []
    return payload


def build_reply_blocks(
    reply: StructuredReply,
    rows: list[dict[str, Any]],
    columns: list[str],
    map_pins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """At most one block under the text: comparison cards, then a map, then figures, then an explainer."""
    if reply.cards:
        return {
            "cards": [card.model_dump() for card in reply.cards],
            "map": None,
            "figures": None,
            "explainer": None,
        }
    place_map = build_place_map(map_pins) if reply.show_map else None
    figures = None if place_map is not None else build_figures(reply.figures, rows, columns)
    explainer = (
        None if place_map is not None or figures is not None else build_explainer(reply.explainer)
    )
    return {"cards": [], "map": place_map, "figures": figures, "explainer": explainer}


def _build_stats_layout(
    figures: list[FigureColumn], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    # Tiles only make sense for a single answer row; several rows belong in a table.
    if len(rows) != 1:
        return None
    row = rows[0]
    tiles = [
        {"label": item.label, "value": format_figure(row.get(item.column), item.unit)}
        for item in figures
        if row.get(item.column) not in (None, "")
    ]
    return {"layout": "stats", "tiles": tiles} if tiles else None


def _build_table_layout(
    figures: list[FigureColumn],
    label_column: str,
    label_title: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    ordered = _oldest_first(rows, label_column) if label_column else rows
    # A run of periods keeps its latest ones; other rows keep the order the lookup gave them.
    shown = (
        ordered[-MAX_FIGURE_ROWS:] if ordered is not rows else rows[:MAX_FIGURE_ROWS]
    )
    figures, caption = _lift_repeated_columns_to_caption(figures, shown)
    if not figures:
        return None
    header = label_title.strip() or _label_header(label_column)
    headers = ([header] if label_column else []) + [item.label for item in figures]
    body = []
    for row in shown:
        cells = [format_figure(row.get(item.column), item.unit) for item in figures]
        if not any(cells):
            continue
        body.append(([_normalize_text(row.get(label_column))] if label_column else []) + cells)
    if len(body) < 2:
        return None
    return {
        "layout": "table",
        "headers": headers,
        "rows": body,
        "caption": caption,
        "hidden_rows": len(ordered) - len(shown),
    }


def _lift_repeated_columns_to_caption(
    figures: list[FigureColumn], rows: list[dict[str, Any]]
) -> tuple[list[FigureColumn], list[str]]:
    """Move a text or year column that reads the same on every row out of the grid.

    "As of May 2026" on each of five rows is one fact; it becomes a caption line instead.
    A repeated number stays, since the same figure across rows is itself worth seeing.
    """
    kept: list[FigureColumn] = []
    caption: list[str] = []
    for item in figures:
        values = {format_figure(row.get(item.column), item.unit) for row in rows}
        if (
            item.unit in _CAPTION_UNITS
            and len(rows) > 1
            and len(values) == 1
            and "" not in values
        ):
            caption.append(f"{item.label}: {values.pop()}")
        else:
            kept.append(item)
    return kept, caption


def _build_bar_layout(
    figure: FigureColumn, label_column: str, rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if not label_column or figure.unit == "text":
        return None
    bars = []
    for row in rows[:MAX_FIGURE_ROWS]:
        value = _to_decimal(row.get(figure.column))
        name = _normalize_text(row.get(label_column))
        if value is None or not name:
            continue
        bars.append(
            {
                "label": name,
                "value": float(value),
                "display": format_figure(value, figure.unit),
            }
        )
    if len(bars) < 2 or any(bar["value"] < 0 for bar in bars):
        return None
    return {
        "layout": "bar",
        "title": figure.label,
        "bars": bars,
        "hidden_rows": max(len(rows) - MAX_FIGURE_ROWS, 0),
    }


def _build_line_layout(
    figures: list[FigureColumn], label_column: str, rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Up to three series over periods, oldest first. Every series shares the first one's unit."""
    if not label_column:
        return None
    unit = figures[0].unit
    if unit == "text":
        return None
    series_columns = [item for item in figures if item.unit == unit][:MAX_LINE_SERIES]
    ordered = _oldest_first(rows, label_column)
    shown = ordered[-MAX_LINE_POINTS:]
    labels = [_normalize_text(row.get(label_column)) for row in shown]
    if not all(labels):
        return None
    series = []
    for item in series_columns:
        points = []
        for row in shown:
            value = _to_decimal(row.get(item.column))
            points.append(
                {"value": float(value), "display": format_figure(value, unit)}
                if value is not None
                else {"value": None, "display": ""}
            )
        if sum(point["value"] is not None for point in points) >= MIN_LINE_POINTS:
            series.append({"name": item.label, "points": points})
    if not series:
        return None
    return {
        "layout": "line",
        "title": series[0]["name"] if len(series) == 1 else "",
        "labels": labels,
        "series": series,
        "hidden_rows": len(ordered) - len(shown),
    }


def _oldest_first(
    rows: list[dict[str, Any]], label_column: str
) -> list[dict[str, Any]]:
    """Rows in time order when every label is a period written as an ISO date or a year.

    Those sort correctly as text. Any other rows come back as the same list, unchanged.
    """
    labels = [_normalize_text(row.get(label_column)) for row in rows]
    if len(labels) > 1 and all(_PERIOD_LABEL_PATTERN.match(label) for label in labels):
        # Records dated after today (a contract keyed in as 2028) are entry errors, not a period.
        today = date.today().isoformat()
        return [
            row
            for label, row in sorted(zip(labels, rows), key=lambda pair: pair[0])
            if label[:10] <= today
        ]
    return rows


_PERIOD_LABEL_PATTERN = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?( Q[1-4])?$")


def format_figure(value: Any, unit: str) -> str:
    """A value as the buyer reads it. Text that is already formatted is kept as is."""
    if value is None or value == "":
        return ""
    if unit == "text":
        return _normalize_text(value)
    number = _to_decimal(value)
    if number is None:
        return _normalize_text(value)
    if unit == "aed":
        return f"AED {_format_aed_amount(number)}"
    if unit == "aed_per_sqft":
        return f"AED {_format_grouped_number(number, 0)}/sqft"
    if unit == "sqft":
        return f"{_format_grouped_number(number, 0)} sqft"
    if unit == "percent":
        return f"{_format_grouped_number(number, 2)}%"
    if unit == "change":
        shown = _format_grouped_number(abs(number), 1)
        if shown == "0":
            return "0%"
        return f"{'▲' if number > 0 else '▼'} {shown}%"
    if unit == "fraction":
        return f"{_format_grouped_number(number * 100, 2)}%"
    if unit == "count":
        return _format_grouped_number(number, 0)
    if unit == "year":
        return str(int(number))
    return _format_grouped_number(number, 2)


def _format_aed_amount(number: Decimal) -> str:
    if abs(number) >= 1_000_000:
        return f"{_format_grouped_number(number / 1_000_000, 2)}M"
    # Small amounts such as service charges keep their fils; rounding them loses the figure.
    return _format_grouped_number(number, 2 if abs(number) < 1_000 else 0)


def _format_grouped_number(number: Decimal, places: int) -> str:
    text = f"{number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        return number if number.is_finite() else None
    if isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except InvalidOperation:
            return None
        return number if number.is_finite() else None
    return None


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""


def _label_header(column: str) -> str:
    words = column.removesuffix("_en").replace("_", " ").strip()
    return words[:1].upper() + words[1:]
