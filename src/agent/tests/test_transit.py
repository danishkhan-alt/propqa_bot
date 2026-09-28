"""Rail stations near listings, and the rail lines a map draws under its pins."""

from __future__ import annotations

from agent.sql.transit import _latlng_path, _RailLineCache, nearest_station_pins


def test_each_listing_and_each_station_it_is_near_is_pinned_once():
    cards = [{"id": "1", "building_name": "Marina Gate"}, {"id": "2", "project_name": "Bay Square"}, {"id": "3"}]
    station = {
        "station_kind": "metro",
        "station_name": "DMCC Metro Station",
        "station_line": "Red Metro line",
        "station_lat": 25.0708,
        "station_lng": 55.1387,
    }
    rows = [
        {"id": 1, "lat": 25.08, "lng": 55.14, "station_km": "0.9", **station},
        {"id": 2, "lat": 25.07, "lng": 55.13, "station_km": "0.3", **station},
        {"id": 3, "lat": 0, "lng": 0, "station_km": "0.1", **station},
    ]
    pins = nearest_station_pins(cards, rows)
    assert [(pin["kind"], pin["label"]) for pin in pins] == [
        ("listing", "Marina Gate"),
        ("listing", "Bay Square"),
        ("metro", "DMCC Metro Station"),
        ("metro", "DMCC Metro Station"),
    ]
    assert pins[1]["detail"] == "0.3 km to DMCC Metro Station"
    assert pins[2]["line"] == "red" and pins[2]["detail"] == "Red Metro line"


def test_a_line_shape_is_read_as_lat_lng_points():
    geojson = '{"type":"LineString","coordinates":[[55.13,25.06],[55.14,25.07]]}'
    assert _latlng_path(geojson) == [[25.06, 55.13], [25.07, 55.14]]
    assert _latlng_path('{"type":"Point","coordinates":[55.1,25.0]}') == []
    assert _latlng_path("not json") == []


def test_rail_lines_are_read_once_and_a_failure_is_retried():
    calls = []

    def broken():
        calls.append("broken")
        raise RuntimeError("warehouse down")

    def working():
        calls.append("working")
        return [{"line": "Red Metro line", "path": [[25.0, 55.1], [25.1, 55.2]]}]

    cache = _RailLineCache()
    assert cache.get(broken) == []
    assert cache.get(working) == cache.get(working)
    assert calls == ["broken", "working"]
