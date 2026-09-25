"""Reply blocks laid out from the lookup rows, and the one-block limit per reply.

The answer model only names columns, labels, and units. Every value shown is copied
from the rows here, so a figure on screen always matches the data.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from agent.schemas.reply import Explainer, FigureColumn, FigureSpec, StructuredReply

MAX_FIGURE_ROWS = 8
MAX_LINE_POINTS = 36
MAX_LINE_SERIES = 3
MIN_LINE_POINTS = 3
# A column repeating one of these in every row is context, such as the period, not a finding.
_CAPTION_UNITS = frozenset({"text", "year"})


def build_figures(
    spec: FigureSpec | None, rows: list[dict[str, Any]], columns: list[str]
) -> dict[str, Any] | None:
    """The UI payload for `spec`, or None when the rows cannot fill it."""
    if spec is None or spec.layout == "none" or not rows:
        return None
    known = set(columns) or set(rows[0])
    figures = [item for item in spec.columns if item.column in known and item.column != spec.label_column]
    if not figures:
        return None
    label_column = spec.label_column if spec.label_column in known else ""
    if spec.layout == "stats":
        return _stats(figures, rows)
    if spec.layout == "table":
        return _table(figures, label_column, spec.label_title, rows)
    if spec.layout == "bar":
        return _bar(figures[0], label_column, rows)
    if spec.layout == "line":
        return _line(figures, label_column, rows)
    return None


def build_explainer(explainer: Explainer | None) -> dict[str, Any] | None:
    if explainer is None or explainer.kind == "none":
        return None
    if not explainer.points and not (explainer.kind == "pros_cons" and explainer.cautions):
        return None
    payload = explainer.model_dump()
    if explainer.kind != "pros_cons":
        payload["cautions"] = []
    return payload


def reply_blocks(reply: StructuredReply, rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    """At most one block under the text: comparison cards, then figures, then an explainer."""
    if reply.cards:
        return {"cards": [card.model_dump() for card in reply.cards], "figures": None, "explainer": None}
    figures = build_figures(reply.figures, rows, columns)
    explainer = None if figures is not None else build_explainer(reply.explainer)
    return {"cards": [], "figures": figures, "explainer": explainer}


def _stats(figures: list[FigureColumn], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
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


def _table(
    figures: list[FigureColumn], label_column: str, label_title: str, rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if len(rows) < 2:
        return None
    shown = rows[:MAX_FIGURE_ROWS]
    figures, caption = _lift_repeated(figures, shown)
    if not figures:
        return None
    header = label_title.strip() or _label_header(label_column)
    headers = ([header] if label_column else []) + [item.label for item in figures]
    body = []
    for row in shown:
        cells = [format_figure(row.get(item.column), item.unit) for item in figures]
        if not any(cells):
            continue
        body.append(([_text(row.get(label_column))] if label_column else []) + cells)
    if len(body) < 2:
        return None
    return {
        "layout": "table",
        "headers": headers,
        "rows": body,
        "caption": caption,
        "hidden_rows": len(rows) - len(shown),
    }


def _lift_repeated(
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
        if item.unit in _CAPTION_UNITS and len(rows) > 1 and len(values) == 1 and "" not in values:
            caption.append(f"{item.label}: {values.pop()}")
        else:
            kept.append(item)
    return kept, caption


def _bar(figure: FigureColumn, label_column: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not label_column or figure.unit == "text":
        return None
    bars = []
    for row in rows[:MAX_FIGURE_ROWS]:
        value = _decimal(row.get(figure.column))
        name = _text(row.get(label_column))
        if value is None or not name:
            continue
        bars.append({"label": name, "value": float(value), "display": format_figure(value, figure.unit)})
    if len(bars) < 2 or any(bar["value"] < 0 for bar in bars):
        return None
    return {
        "layout": "bar",
        "title": figure.label,
        "bars": bars,
        "hidden_rows": max(len(rows) - MAX_FIGURE_ROWS, 0),
    }


def _line(figures: list[FigureColumn], label_column: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Up to three series over periods, oldest first. Every series shares the first one's unit."""
    if not label_column:
        return None
    unit = figures[0].unit
    if unit == "text":
        return None
    series_columns = [item for item in figures if item.unit == unit][:MAX_LINE_SERIES]
    ordered = _oldest_first(rows, label_column)
    shown = ordered[-MAX_LINE_POINTS:]
    labels = [_text(row.get(label_column)) for row in shown]
    if not all(labels):
        return None
    series = []
    for item in series_columns:
        points = []
        for row in shown:
            value = _decimal(row.get(item.column))
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
        "hidden_rows": len(rows) - len(shown),
    }


def _oldest_first(rows: list[dict[str, Any]], label_column: str) -> list[dict[str, Any]]:
    """Rows in time order. Periods written as ISO dates or years sort as text; others keep their order."""
    labels = [_text(row.get(label_column)) for row in rows]
    if len(labels) > 1 and all(_PERIOD.match(label) for label in labels) and labels[0] > labels[-1]:
        return list(reversed(rows))
    return list(rows)


_PERIOD = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?( Q[1-4])?$")


def format_figure(value: Any, unit: str) -> str:
    """A value as the buyer reads it. Text that is already formatted is kept as is."""
    if value is None or value == "":
        return ""
    if unit == "text":
        return _text(value)
    number = _decimal(value)
    if number is None:
        return _text(value)
    if unit == "aed":
        return f"AED {_money(number)}"
    if unit == "aed_per_sqft":
        return f"AED {_grouped(number, 0)}/sqft"
    if unit == "sqft":
        return f"{_grouped(number, 0)} sqft"
    if unit == "percent":
        return f"{_grouped(number, 2)}%"
    if unit == "change":
        shown = _grouped(abs(number), 1)
        if shown == "0":
            return "0%"
        return f"{'▲' if number > 0 else '▼'} {shown}%"
    if unit == "fraction":
        return f"{_grouped(number * 100, 2)}%"
    if unit == "count":
        return _grouped(number, 0)
    if unit == "year":
        return str(int(number))
    return _grouped(number, 2)


def _money(number: Decimal) -> str:
    if abs(number) >= 1_000_000:
        return f"{_grouped(number / 1_000_000, 2)}M"
    # Small amounts such as service charges keep their fils; rounding them loses the figure.
    return _grouped(number, 2 if abs(number) < 1_000 else 0)


def _grouped(number: Decimal, places: int) -> str:
    text = f"{number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _decimal(value: Any) -> Decimal | None:
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


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""


def _label_header(column: str) -> str:
    words = column.removesuffix("_en").replace("_", " ").strip()
    return words[:1].upper() + words[1:]
