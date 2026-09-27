"""Map pins for a reply about where places are: stations, stops, schools, a picked listing.

Every pin is copied from the data here. The answer model only says whether a map helps,
so a pin on screen always sits where the warehouse puts it.

Lookup rows carry coordinates as a latitude and longitude column pair. Catalog tables name
them many ways (lat/long, lat/lng, station_location_latitude, project_lat, even latitiude),
so a pair is found by its name parts, not a fixed list. The pair is taken out of the rows
before the answer model reads them: raw coordinates are noise in a reply.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_MAP_PINS = 40
# Anything outside the UAE is a bad record (a swapped or zeroed pair), not a place to show.
_UAE_LATITUDE = (22.5, 26.5)
_UAE_LONGITUDE = (51.0, 56.5)
_LATITUDE_WORDS = frozenset({"lat", "latitude", "latitiude"})
_LONGITUDE_WORDS = frozenset({"lng", "lon", "long", "longitude", "longitiude"})
_TRAILING_WORDS = frozenset({"attr"})
# A road or cycle track row has a start and an end point; neither is where the row "is".
_SEGMENT_WORDS = frozenset({"start", "end"})
_ARABIC_WORDS = frozenset({"ar", "arabic"})
_ID_WORDS = frozenset({"id", "num", "number", "code"})


@dataclass(frozen=True)
class CoordinatePair:
    latitude: str
    longitude: str


def find_coordinate_pair(columns: list[str]) -> CoordinatePair | None:
    """The first latitude column with a longitude column of the same name otherwise."""
    longitudes: dict[tuple[tuple[str, ...], tuple[str, ...]], str] = {}
    for column in columns:
        key = _coordinate_key(column, _LONGITUDE_WORDS)
        if key is not None:
            longitudes.setdefault(key, column)
    for column in columns:
        key = _coordinate_key(column, _LATITUDE_WORDS)
        if key is not None and key in longitudes:
            return CoordinatePair(latitude=column, longitude=longitudes[key])
    return None


def _coordinate_key(
    column: str, words: frozenset[str]
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """(words before, words after) the coordinate word, or None when the column is not one."""
    parts = column.casefold().split("_")
    for index, part in enumerate(parts):
        if part not in words:
            continue
        before, after = tuple(parts[:index]), tuple(parts[index + 1 :])
        if set(after) <= _TRAILING_WORDS and not _SEGMENT_WORDS & set(before):
            return before, after
    return None


def is_coordinate_column(column: str) -> bool:
    return (
        _coordinate_key(column, _LATITUDE_WORDS) is not None
        or _coordinate_key(column, _LONGITUDE_WORDS) is not None
    )


def split_place_rows(
    rows: list[dict[str, Any]], columns: list[str]
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Rows and columns without coordinates, and a pin for each row that had a valid pair."""
    names = list(columns) or list(rows[0] if rows else [])
    pair = find_coordinate_pair(names)
    if pair is None:
        return rows, columns, []
    kept_columns = [column for column in names if not is_coordinate_column(column)]
    label_column = _label_column(kept_columns, rows)
    detail_column = _detail_column(kept_columns, rows, label_column)
    pins: list[dict[str, Any]] = []
    for row in rows:
        label = _text(row.get(label_column)) if label_column else ""
        pin = map_pin(
            row.get(pair.latitude),
            row.get(pair.longitude),
            label=label,
            detail=_text(row.get(detail_column)) if detail_column else "",
            kind="place",
        )
        if pin is not None and label:
            pins.append(pin)
    stripped = [
        {key: value for key, value in row.items() if not is_coordinate_column(key)}
        for row in rows
    ]
    return stripped, kept_columns if columns else [], pins


def _label_column(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """The column that names each row: an English name or title, else the first text column."""
    texts = [column for column in columns if _is_text_column(column, rows)]
    for words in (("name", "en"), ("name", "english"), ("name",), ("title",)):
        for column in texts:
            if set(words) <= set(column.casefold().split("_")):
                return column
    return texts[0] if texts else ""


def _detail_column(columns: list[str], rows: list[dict[str, Any]], label_column: str) -> str:
    """A second text column shown under the name, such as the metro line or the community."""
    for column in columns:
        if column != label_column and _is_text_column(column, rows):
            return column
    return ""


def _is_text_column(column: str, rows: list[dict[str, Any]]) -> bool:
    words = set(column.casefold().split("_"))
    if words & (_ARABIC_WORDS | _ID_WORDS):
        return False
    values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
    return bool(values) and all(isinstance(value, str) and _to_float(value) is None for value in values)


def map_pin(
    latitude: Any, longitude: Any, *, label: str, detail: str = "", kind: str
) -> dict[str, Any] | None:
    """One pin, or None when the pair is missing or falls outside the UAE."""
    lat, lng = _to_float(latitude), _to_float(longitude)
    if lat is None or lng is None:
        return None
    if not (_UAE_LATITUDE[0] <= lat <= _UAE_LATITUDE[1] and _UAE_LONGITUDE[0] <= lng <= _UAE_LONGITUDE[1]):
        return None
    return {"lat": round(lat, 6), "lng": round(lng, 6), "label": label, "detail": detail, "kind": kind}


def build_place_map(pins: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The UI payload: each place once, in the order given, capped for a readable map.

    A place on several rows (an interchange station, one row per line) keeps every detail.
    """
    unique: list[dict[str, Any]] = []
    seen: dict[tuple[str, float, float], dict[str, Any]] = {}
    for pin in pins or []:
        key = (pin["label"].casefold(), round(pin["lat"], 4), round(pin["lng"], 4))
        kept = seen.get(key)
        if kept is None:
            seen[key] = dict(pin)
            unique.append(seen[key])
        elif pin["detail"] and pin["detail"] not in kept["detail"].split(" · "):
            kept["detail"] = " · ".join(part for part in (kept["detail"], pin["detail"]) if part)
    if not unique:
        return None
    return {"pins": unique[:MAX_MAP_PINS], "hidden_pins": max(len(unique) - MAX_MAP_PINS, 0)}


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return float(number) if number.is_finite() else None


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""
