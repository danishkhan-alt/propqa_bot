"""What an advert says beyond its card: description, features, amenities, views, and surroundings.

Read when the user picks listings in the UI and asks about them. One fixed statement, so the
turn needs no SQL model. Distances come from PostGIS, measured from the listing's pin.
Coordinates become map pins and never enter the facts the answer model reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.reply.place_map import map_pin
from agent.sql.cards import ListingLoader, fetch_listing_cards, prompt_listing_facts, to_json_number
from agent.sql.execute import run_against_warehouse
from common.logger import get_logger

logger = get_logger("agent.sql")

# Matches the frontend's attach limit. Each listing adds its description to the prompt.
MAX_FOCUSED_LISTINGS = 8
MAX_DESCRIPTION_CHARS = 1500
MAX_NEARBY_PLACES_PER_KIND = 3

_COORDINATE = r"^\s*-?[0-9]+(\.[0-9]+)?\s*$"

LISTING_DETAILS_SQL = f"""
WITH wanted AS (
    SELECT id, ord FROM unnest(%(ids)s::bigint[]) WITH ORDINALITY AS w(id, ord)
)
SELECT
    p.id,
    NULLIF(TRIM(REPLACE(LEFT(p.detail_en, %(description_chars)s), E'\\r', '')), '') AS description,
    p.is_free_hold,
    p.ownership,
    p.is_parking_available,
    p.no_of_parkings,
    p.floors,
    p.layout_type,
    p.is_corner,
    p.property_age,
    p.plot_area,
    p.rent_availability,
    p.no_of_cheques,
    p.permit_number,
    p.is_verified,
    ST_Y(here.pin) AS lat,
    ST_X(here.pin) AS lng,
    amenity.names AS amenities,
    outlook.names AS views,
    nearby.places AS nearby_places,
    metro.name AS metro_station,
    metro.line AS metro_line,
    metro.km AS metro_km,
    metro.lat AS metro_lat,
    metro.lng AS metro_lng
FROM wanted w
JOIN public.properties p ON p.id = w.id AND p.deleted_at IS NULL
LEFT JOIN LATERAL (
    SELECT ST_SetSRID(ST_MakePoint(p.lng::float8, p.lat::float8), 4326) AS pin
    WHERE p.lat ~ '{_COORDINATE}' AND p.lng ~ '{_COORDINATE}'
      AND p.lat::float8 <> 0 AND p.lng::float8 <> 0
) here ON true
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT a.title_en) AS names
    FROM public.amenity_property ap
    JOIN public.amenities a ON a.id = ap.amenity_id
    WHERE ap.property_id = p.id AND NULLIF(TRIM(a.title_en), '') IS NOT NULL
) amenity ON true
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT v.title_en) AS names
    FROM public.property_view pv
    JOIN public.views v ON v.id = pv.view_id
    WHERE pv.property_id = p.id AND NULLIF(TRIM(v.title_en), '') IS NOT NULL
) outlook ON true
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(kind, places) AS places
    FROM (
        SELECT kind.key AS kind, jsonb_agg(
            jsonb_build_object('name', near.name, 'km', near.km, 'lat', near.lat, 'lng', near.lng)
            ORDER BY near.km
        ) AS places
        FROM jsonb_each(
            CASE WHEN json_typeof(p.near_by_locations) = 'object' THEN p.near_by_locations::jsonb END
        ) kind
        CROSS JOIN LATERAL (
            SELECT
                place->>'name' AS name,
                (place->>'latitude')::float8 AS lat,
                (place->>'longitude')::float8 AS lng,
                ROUND((ST_DistanceSphere(
                    here.pin,
                    ST_SetSRID(ST_MakePoint((place->>'longitude')::float8, (place->>'latitude')::float8), 4326)
                ) / 1000)::numeric, 1) AS km
            FROM jsonb_array_elements(CASE WHEN jsonb_typeof(kind.value) = 'array' THEN kind.value END) place
            WHERE NULLIF(TRIM(place->>'name'), '') IS NOT NULL
              AND place->>'latitude' ~ '{_COORDINATE}' AND place->>'longitude' ~ '{_COORDINATE}'
            ORDER BY km NULLS LAST
            LIMIT %(nearby_per_kind)s
        ) near
        GROUP BY kind.key
    ) grouped
) nearby ON true
LEFT JOIN LATERAL (
    SELECT
        m.location_name_english AS name,
        m.line_name AS line,
        m.station_location_latitude AS lat,
        m.station_location_longitude AS lng,
        ROUND((ST_DistanceSphere(
            here.pin,
            ST_SetSRID(ST_MakePoint(m.station_location_longitude::float8, m.station_location_latitude::float8), 4326)
        ) / 1000)::numeric, 1) AS km
    FROM chatbot_ai.metro_stations m
    WHERE here.pin IS NOT NULL
      AND m.station_closing_date IS NULL
      AND m.station_location_latitude IS NOT NULL
      AND m.station_location_longitude IS NOT NULL
    ORDER BY km
    LIMIT 1
) metro ON true
ORDER BY w.ord
"""


class ListingDetailLoader(Protocol):
    """Returns one warehouse row of advert details per listing id it found. Tests pass a fake."""

    def __call__(self, ids: list[int]) -> list[dict[str, Any]]: ...


def fetch_listing_detail_rows(ids: list[int]) -> list[dict[str, Any]]:
    page = run_against_warehouse(
        LISTING_DETAILS_SQL,
        {
            "ids": ids,
            "description_chars": MAX_DESCRIPTION_CHARS,
            "nearby_per_kind": MAX_NEARBY_PLACES_PER_KIND,
        },
    )
    return page.rows


@dataclass(frozen=True)
class FocusedListings:
    """Facts for the answer model, and the pins a map of these listings would show."""

    facts: list[dict[str, Any]] = field(default_factory=list)
    map_pins: list[dict[str, Any]] = field(default_factory=list)


def fetch_focused_listings(
    ids: list[int],
    card_loader: ListingLoader,
    detail_loader: ListingDetailLoader,
) -> FocusedListings:
    """Card facts plus advert details for each listing that still exists, in the order given."""
    ids = ids[:MAX_FOCUSED_LISTINGS]
    if not ids:
        return FocusedListings()
    try:
        details = {str(row.get("id")): row for row in detail_loader(ids) or [] if row.get("id") is not None}
    except Exception:
        logger.warning("listing.details failed", exc_info=True)
        details = {}
    # An id the loader could not fill comes back as an id-only card: that listing is gone.
    cards = [card for card in fetch_listing_cards([str(item) for item in ids], card_loader) if len(card) > 1]
    facts: list[dict[str, Any]] = []
    pins: list[dict[str, Any]] = []
    for card, fact in zip(cards, prompt_listing_facts(cards)):
        detail = details.get(card["id"]) or {}
        fact.update(_detail_facts(detail))
        facts.append(fact)
        pins.extend(_listing_map_pins(card, detail))
    return FocusedListings(facts=facts, map_pins=pins)


def _detail_facts(row: dict[str, Any]) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "description": row.get("description"),
        "freehold": row.get("is_free_hold"),
        "ownership": row.get("ownership"),
        "parking_available": row.get("is_parking_available"),
        "parking_spaces": row.get("no_of_parkings"),
        "floor": row.get("floors"),
        "layout": row.get("layout_type"),
        "corner_unit": row.get("is_corner") or None,
        "age_years": row.get("property_age"),
        "plot_size_sqft": to_json_number(row.get("plot_area")),
        "available_from": row.get("rent_availability"),
        "rent_cheques": row.get("no_of_cheques"),
        "permit_number": row.get("permit_number"),
        "verified_listing": row.get("is_verified") or None,
        "amenities": sorted(row.get("amenities") or []),
        "views": sorted(row.get("views") or []),
        "nearby_places": _nearby_places(row.get("nearby_places")),
        "nearest_metro": _nearest_metro_fact(row),
    }
    return {key: value for key, value in fact.items() if value not in (None, "", [], {})}


def _nearby_places(value: Any) -> dict[str, list[dict[str, Any]]]:
    """Nearest few places of each kind (schools, parks, ...) with their distance in km."""
    if not isinstance(value, dict):
        return {}
    places: dict[str, list[dict[str, Any]]] = {}
    for kind, items in value.items():
        named = [_nearby_place_fact(item) for item in items or [] if isinstance(item, dict) and item.get("name")]
        if named:
            places[str(kind)] = named
    return places


def _nearby_place_fact(item: dict[str, Any]) -> dict[str, Any]:
    place = {"name": item["name"], "km": to_json_number(item.get("km"))}
    return {key: value for key, value in place.items() if value is not None}


def _nearest_metro_fact(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row.get("metro_station"):
        return None
    metro = {"station": row["metro_station"], "line": row.get("metro_line"), "km": to_json_number(row.get("metro_km"))}
    return {key: value for key, value in metro.items() if value is not None}


def _listing_map_pins(card: dict[str, Any], row: dict[str, Any]) -> list[dict[str, Any]]:
    """The listing, its nearest metro, and the nearby places, each with its distance.

    Nearby places keep no kind: the advert's grouping is noisy (a gym under schools), so a
    pin names only the place itself.
    """
    name = card.get("building_name") or card.get("project_name") or card.get("title_en") or "This listing"
    pins = [
        map_pin(
            row.get("lat"),
            row.get("lng"),
            label=str(name),
            detail=str(card.get("master_project_name") or ""),
            kind="listing",
        )
    ]
    metro = _nearest_metro_fact(row)
    if metro is not None:
        detail = " · ".join(
            part for part in (metro.get("line"), _distance_text(metro.get("km"))) if part
        )
        pins.append(map_pin(row.get("metro_lat"), row.get("metro_lng"), label=metro["station"], detail=detail, kind="metro"))
    places = row.get("nearby_places")
    for items in places.values() if isinstance(places, dict) else []:
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("name"):
                pins.append(
                    map_pin(
                        item.get("lat"),
                        item.get("lng"),
                        label=str(item["name"]),
                        detail=_distance_text(to_json_number(item.get("km"))),
                        kind="nearby",
                    )
                )
    return [pin for pin in pins if pin is not None]


def _distance_text(km: Any) -> str:
    return f"{km} km away" if km is not None else ""
