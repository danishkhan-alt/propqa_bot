"""Rail stations and lines, for listings near a station and for drawing the lines on a map.

Stations come from the RTA metro and tram station tables, one row per station and line. The
line shapes come from the *_lines_gis tables, which are incomplete: the Red line is whole,
the Green line is a stub, and the tram is short fragments. A shape counts as a line only
when it runs past at least two stations, so stubs and fragments drop out on the data alone,
and it takes the name of the line most of those stations are on.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Protocol

from agent.enums.listing import NearStation
from agent.reply.place_map import map_pin, rail_line_key
from agent.sql.cards import listing_display_name, to_json_number
from agent.sql.execute import run_against_warehouse
from agent.sql.listing_sql_fragments import (
    COORDINATE_PATTERN,
    LISTING_HAS_PIN_SQL,
    LISTING_PIN_SQL,
)
from common.logger import get_logger

logger = get_logger("agent.sql")

STATION_KINDS: dict[NearStation, tuple[str, ...]] = {
    NearStation.METRO: ("metro",),
    NearStation.TRAM: ("tram",),
    NearStation.METRO_OR_TRAM: ("metro", "tram"),
}
STATION_LABELS = {
    NearStation.METRO: "a metro station",
    NearStation.TRAM: "a tram stop",
    NearStation.METRO_OR_TRAM: "a metro or tram station",
}
# A shape passes a station when the platform is this close to the track.
_STATION_ON_LINE_METERS = 150
_MIN_STATIONS_ON_LINE = 2
# About 20 m at Dubai's latitude: the drawn line keeps its shape at a fraction of the points.
_LINE_SIMPLIFY_DEGREES = 0.0002

STATIONS_SQL = f"""
    SELECT 'metro' AS kind, location_name_english AS name, line_name AS line,
           ST_SetSRID(ST_MakePoint(station_location_longitude::float8, station_location_latitude::float8), 4326) AS pin
    FROM chatbot_ai.metro_stations
    WHERE station_closing_date IS NULL
      AND station_location_latitude::text ~ '{COORDINATE_PATTERN}'
      AND station_location_longitude::text ~ '{COORDINATE_PATTERN}'
    UNION ALL
    SELECT 'tram', location_name_english, line_name,
           ST_SetSRID(ST_MakePoint(station_location_longitude::float8, station_location_latitude::float8), 4326)
    FROM chatbot_ai.tram_stations
    WHERE station_closing_date IS NULL
      AND station_location_latitude::text ~ '{COORDINATE_PATTERN}'
      AND station_location_longitude::text ~ '{COORDINATE_PATTERN}'
"""


def near_station_clause(near: NearStation, km: float, params: dict[str, Any]) -> str:
    """A WHERE condition: the listing has a pin within `km` of a station of that kind."""
    params["station_kinds"] = list(STATION_KINDS[near])
    params["station_meters"] = km * 1000
    return (
        f"({LISTING_HAS_PIN_SQL} AND EXISTS (SELECT 1 FROM ({STATIONS_SQL}) station "
        "WHERE station.kind = ANY(%(station_kinds)s) "
        f"AND ST_DistanceSphere({LISTING_PIN_SQL}, station.pin) <= %(station_meters)s))"
    )


NEAREST_STATION_SQL = f"""
WITH wanted AS (
    SELECT id, ord FROM unnest(%(ids)s::bigint[]) WITH ORDINALITY AS w(id, ord)
)
SELECT
    p.id,
    p.lat::float8 AS lat,
    p.lng::float8 AS lng,
    station.kind AS station_kind,
    station.name AS station_name,
    station.line AS station_line,
    ST_Y(station.pin) AS station_lat,
    ST_X(station.pin) AS station_lng,
    ROUND((station.meters / 1000)::numeric, 1) AS station_km
FROM wanted w
JOIN public.properties p ON p.id = w.id AND {LISTING_HAS_PIN_SQL}
CROSS JOIN LATERAL (
    SELECT s.*, ST_DistanceSphere({LISTING_PIN_SQL}, s.pin) AS meters
    FROM ({STATIONS_SQL}) s
    WHERE s.kind = ANY(%(station_kinds)s)
    ORDER BY meters
    LIMIT 1
) station
ORDER BY w.ord
"""


class NearestStationLoader(Protocol):
    """Each listing's pin and its nearest station of the kinds asked for. Tests pass a fake."""

    def __call__(self, ids: list[int], kinds: list[str]) -> list[dict[str, Any]]: ...


def fetch_nearest_station_rows(ids: list[int], kinds: list[str]) -> list[dict[str, Any]]:
    return run_against_warehouse(NEAREST_STATION_SQL, {"ids": ids, "station_kinds": kinds}).rows


def nearest_station_pins(cards: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each listing, then the stations they are near, each station once.

    A listing pin says how far its station is; the station pin says its line.
    """
    by_id = {str(row.get("id")): row for row in rows if row.get("id") is not None}
    listings: list[dict[str, Any]] = []
    stations: list[dict[str, Any]] = []
    for card in cards:
        row = by_id.get(str(card.get("id")))
        if row is None:
            continue
        station = str(row.get("station_name") or "")
        km = to_json_number(row.get("station_km"))
        listing = map_pin(
            row.get("lat"),
            row.get("lng"),
            label=listing_display_name(card),
            detail=f"{km} km to {station}" if station and km is not None else "",
            kind="listing",
            property_id=str(card["id"]),
        )
        if listing is None:
            continue
        listings.append(listing)
        stop = map_pin(
            row.get("station_lat"),
            row.get("station_lng"),
            label=station,
            detail=str(row.get("station_line") or ""),
            kind=str(row.get("station_kind") or "metro"),
            line=rail_line_key(row.get("station_line")),
        )
        if stop is not None and station:
            stations.append(stop)
    return [*listings, *stations]


RAIL_LINES_SQL = f"""
WITH shapes AS (
    SELECT ST_GeomFromText(coordinates, 4326) AS shape
    FROM chatbot_ai.metro_lines_gis
    WHERE coordinates LIKE 'LINESTRING(%%'
    UNION ALL
    SELECT ST_GeomFromText(coordinates, 4326)
    FROM chatbot_ai.tram_lines_gis
    WHERE coordinates LIKE 'LINESTRING(%%'
),
named AS (
    SELECT shapes.shape, passed.line, passed.stations
    FROM shapes
    CROSS JOIN LATERAL (
        SELECT station.line, count(*) AS stations
        FROM ({STATIONS_SQL}) station
        WHERE ST_DWithin(station.pin::geography, shapes.shape::geography, %(on_line_meters)s)
        GROUP BY station.line
        ORDER BY stations DESC
        LIMIT 1
    ) passed
)
SELECT line, ST_AsGeoJSON(ST_Simplify(shape, %(simplify)s)) AS path
FROM named
WHERE stations >= %(min_stations)s
"""


class RailLineLoader(Protocol):
    """Every drawable line as {"line": name, "path": [[lat, lng], ...]}. Tests pass a fake."""

    def __call__(self) -> list[dict[str, Any]]: ...


def fetch_rail_lines() -> list[dict[str, Any]]:
    page = run_against_warehouse(
        RAIL_LINES_SQL,
        {
            "on_line_meters": _STATION_ON_LINE_METERS,
            "min_stations": _MIN_STATIONS_ON_LINE,
            "simplify": _LINE_SIMPLIFY_DEGREES,
        },
    )
    lines: list[dict[str, Any]] = []
    for row in page.rows:
        path = _latlng_path(row.get("path"))
        if row.get("line") and len(path) >= 2:
            lines.append({"line": str(row["line"]), "path": path})
    return lines


def _latlng_path(geojson: Any) -> list[list[float]]:
    """GeoJSON LineString [lng, lat] points as [lat, lng], the order a map takes them in."""
    try:
        shape = json.loads(geojson) if isinstance(geojson, str) else None
    except ValueError:
        return []
    if not isinstance(shape, dict) or shape.get("type") != "LineString":
        return []
    return [[round(point[1], 6), round(point[0], 6)] for point in shape.get("coordinates") or [] if len(point) >= 2]


class _RailLineCache:
    """The lines never change while the app runs, so they are read once per process.

    A failed read is not kept: the next map asks again, and until then maps have no lines.
    """

    def __init__(self) -> None:
        self._lines: list[dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def get(self, loader: RailLineLoader = fetch_rail_lines) -> list[dict[str, Any]]:
        if self._lines is not None:
            return self._lines
        with self._lock:
            if self._lines is None:
                try:
                    self._lines = loader()
                except Exception:
                    logger.warning("transit.rail_lines failed", exc_info=True)
                    return []
                logger.info("transit.rail_lines", extra={"extra_data": {"lines": [line["line"] for line in self._lines]}})
            return self._lines


_rail_lines = _RailLineCache()


def get_rail_lines() -> list[dict[str, Any]]:
    return _rail_lines.get()
