"""Map pins for a reply about where places are: stations, stops, schools, a picked listing.

Every pin is copied from the data here. The answer model only says whether a map helps,
so a pin on screen always sits where the warehouse puts it.

Lookup rows carry coordinates as a latitude and longitude column pair. Catalog tables name
them many ways (lat/long, lat/lng, station_location_latitude, project_lat, even latitiude),
so a pair is found by its name parts, not a fixed list. The pair is taken out of the rows
before the answer model reads them: raw coordinates are noise in a reply.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_MAP_PINS = 40
# A line is drawn when a pin sits on it: a station, or a listing right by the track.
LINE_NEAR_PIN_METERS = 150
_EARTH_RADIUS_METERS = 6_371_000
# Rail line names as the RTA tables write them, to the key the map colors them by.
_RAIL_LINE_WORDS = (("red", "red"), ("green", "green"), ("tram", "tram"))
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
    latitude: Any,
    longitude: Any,
    *,
    label: str,
    detail: str = "",
    kind: str,
    line: str = "",
    property_id: str = "",
) -> dict[str, Any] | None:
    """One pin, or None when the pair is missing or falls outside the UAE.

    `line` is a station's rail line, as rail_line_key gives it. `property_id` ties a
    listing pin to its photo card.
    """
    lat, lng = _to_float(latitude), _to_float(longitude)
    if lat is None or lng is None or not _in_uae(lat, lng):
        return None
    pin = {"lat": round(lat, 6), "lng": round(lng, 6), "label": label, "detail": detail, "kind": kind}
    if line:
        pin["line"] = line
    if property_id:
        pin["property_id"] = property_id
    return pin


def rail_line_key(name: Any) -> str:
    """red, green, or tram for an RTA line name such as "Red Metro line"; empty otherwise."""
    words = str(name or "").casefold().split()
    return next((key for word, key in _RAIL_LINE_WORDS if word in words), "")


def build_place_map(
    pins: list[dict[str, Any]] | None, lines: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """The UI payload: each place once, in the order given, capped for a readable map.

    A place on several rows (an interchange station, one row per line) keeps every detail.
    Listings are told apart by id: two units in one tower share a name and a pin.
    Rail lines come along only when a pin shown sits on them.
    """
    unique: list[dict[str, Any]] = []
    seen: dict[tuple, dict[str, Any]] = {}
    for pin in pins or []:
        key = (
            ("listing", pin["property_id"])
            if pin.get("property_id")
            else (pin["label"].casefold(), round(pin["lat"], 4), round(pin["lng"], 4))
        )
        kept = seen.get(key)
        if kept is None:
            seen[key] = dict(pin)
            unique.append(seen[key])
        elif pin["detail"] and pin["detail"] not in kept["detail"].split(" · "):
            kept["detail"] = " · ".join(part for part in (kept["detail"], pin["detail"]) if part)
    if not unique:
        return None
    shown = unique[:MAX_MAP_PINS]
    return {
        "pins": shown,
        "hidden_pins": max(len(unique) - MAX_MAP_PINS, 0),
        "lines": [
            {"line": rail_line_key(line["line"]), "name": line["line"], "path": line["path"]}
            for line in lines or []
            if any(_meters_to_path(pin, line["path"]) <= LINE_NEAR_PIN_METERS for pin in shown)
        ],
    }


def _meters_to_path(pin: dict[str, Any], path: list[list[float]]) -> float:
    """Shortest distance from the pin to a [lat, lng] polyline, flat-earth: fine at city scale."""
    scale = math.cos(math.radians(pin["lat"]))

    def xy(lat: float, lng: float) -> tuple[float, float]:
        return (
            math.radians(lng - pin["lng"]) * scale * _EARTH_RADIUS_METERS,
            math.radians(lat - pin["lat"]) * _EARTH_RADIUS_METERS,
        )

    points = [xy(lat, lng) for lat, lng in path]
    if len(points) == 1:
        return math.hypot(*points[0])
    return min(_distance_to_segment(start, end) for start, end in zip(points, points[1:]))


def _distance_to_segment(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Distance from the origin to the segment start-end."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, -(start[0] * dx + start[1] * dy) / length))
    return math.hypot(start[0] + t * dx, start[1] + t * dy)


def _in_uae(lat: float, lng: float) -> bool:
    return _UAE_LATITUDE[0] <= lat <= _UAE_LATITUDE[1] and _UAE_LONGITUDE[0] <= lng <= _UAE_LONGITUDE[1]


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
