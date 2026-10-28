"""Independent listing truth and fact sheets. These queries do not call the search builder.

A place matches the same three ways a listing can point at it: a locations_v2 id, a legacy
locations id, or one comma-separated part of address_en. A substring of the address is not
a match, so "Dubai Marina Mall" is not Dubai Marina.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from agent.sql.execute import fetch_reference_rows

_PLACE_CTE = """
WITH RECURSIVE v2_place AS (
    SELECT id FROM public.locations_v2 WHERE lower(title_en) = ANY(%(names)s)
    UNION SELECT child.id FROM public.locations_v2 child JOIN v2_place parent ON child.parent_id = parent.id
), legacy_place AS (
    SELECT id FROM public.locations WHERE lower(name_en) = ANY(%(names)s)
    UNION SELECT child.id FROM public.locations child JOIN legacy_place parent ON child.parent_id = parent.id
)
"""

_ADDRESS_PARTS = """
EXISTS (
    SELECT 1 FROM unnest(string_to_array(lower(COALESCE(p.address_en, '')), ',')) AS part
    WHERE trim(part) = ANY(%(names)s)
)
"""

PLACE_LISTINGS_SQL = (
    _PLACE_CTE
    + """
SELECT p.id
FROM public.properties p
WHERE p.status = 'active' AND p.deleted_at IS NULL
  AND (
    p.location_v2_id IN (SELECT id FROM v2_place)
    OR p.location_master_project_id IN (SELECT id FROM legacy_place)
    OR p.location_project_id IN (SELECT id FROM legacy_place)
    OR p.location_building_id IN (SELECT id FROM legacy_place)
    OR """
    + _ADDRESS_PARTS
    + """
  )
  AND ({where})
"""
)

ANY_LISTINGS_SQL = (
    "SELECT p.id FROM public.properties p "
    "WHERE p.status = 'active' AND p.deleted_at IS NULL AND ({where})"
)

_FACT_SQL = (
    _PLACE_CTE
    + """
SELECT
    p.id,
    p.title_en AS title,
    p.purpose,
    p.rooms,
    COALESCE(p.price_max, p.price_min) AS asking_price_aed,
    p.area AS area_sqft,
    p.developer,
    p.address_en AS address,
    COALESCE(lv.title_en, master.name_en) AS community,
    (p.location_v2_id IN (SELECT id FROM v2_place)) AS place_v2,
    (
        p.location_master_project_id IN (SELECT id FROM legacy_place)
        OR p.location_project_id IN (SELECT id FROM legacy_place)
        OR p.location_building_id IN (SELECT id FROM legacy_place)
    ) AS place_legacy,
    """
    + _ADDRESS_PARTS
    + """ AS place_address,
    COALESCE((
        SELECT array_agg(c.name_en ORDER BY c.name_en)
        FROM public.category_property cp
        JOIN public.categories c ON c.id = cp.category_id
        WHERE cp.property_id = p.id
    ), ARRAY[]::text[]) AS categories,
    COALESCE((
        SELECT array_agg(a.title_en ORDER BY a.title_en)
        FROM public.amenity_property ap
        JOIN public.amenities a ON a.id = ap.amenity_id
        WHERE ap.property_id = p.id
    ), ARRAY[]::text[]) AS amenities,
    COALESCE((
        SELECT array_agg(v.title_en ORDER BY v.title_en)
        FROM public.property_view pv
        JOIN public.views v ON v.id = pv.view_id
        WHERE pv.property_id = p.id
    ), ARRAY[]::text[]) AS views,
    CASE
        WHEN %(text_query)s::text IS NULL THEN NULL
        ELSE p.search_vector @@ websearch_to_tsquery('english', %(text_query)s::text)
    END AS text_match,
    EXISTS (
        SELECT 1 FROM public.users vu
        WHERE vu.id = p.user_id
          AND vu.verification_status = 'approved'
          AND vu.deleted_at IS NULL
    ) AS verified_agent,
    ({where}) AS matches_filters
FROM public.properties p
LEFT JOIN public.locations_v2 lv ON lv.id = p.location_v2_id
LEFT JOIN public.locations master ON master.id = p.location_master_project_id
WHERE p.id = ANY(%(ids)s::bigint[])
"""
)


def fetch_truth_ids(expected: dict, where: str) -> set[str]:
    """Listing ids a correct search for this case returns."""
    names = _place_names(expected)
    if names:
        rows = fetch_reference_rows(PLACE_LISTINGS_SQL.format(where=where), {"names": names})
    else:
        rows = fetch_reference_rows(ANY_LISTINGS_SQL.format(where=where))
    return {str(row["id"]) for row in rows}


def fetch_fact_sheet(listing_ids: list[str], expected: dict, where: str) -> list[dict[str, Any]]:
    """One fact row per returned id, in the order the search returned them."""
    numeric = [int(item) for item in listing_ids if str(item).isdigit()]
    by_id: dict[str, dict[str, Any]] = {}
    if numeric:
        rows = fetch_reference_rows(
            _FACT_SQL.format(where=where),
            {
                "names": _place_names(expected),
                "ids": numeric,
                "text_query": expected.get("text") or None,
            },
        )
        by_id = {str(row["id"]): _fact(row) for row in rows}
    sheet: list[dict[str, Any]] = []
    for listing_id in listing_ids:
        fact = by_id.get(str(listing_id))
        if fact is None:
            sheet.append({"id": str(listing_id), "matches_filters": False, "missing": True})
        else:
            sheet.append(fact)
    return sheet


def _place_names(expected: dict) -> list[str]:
    return [str(name).lower() for name in expected.get("place") or []]


def _fact(row: dict[str, Any]) -> dict[str, Any]:
    links = [
        name
        for name, flag in (
            ("v2", row.get("place_v2")),
            ("legacy", row.get("place_legacy")),
            ("address", row.get("place_address")),
        )
        if flag
    ]
    fact = {
        "id": str(row["id"]),
        "title": row.get("title"),
        "purpose": row.get("purpose"),
        "rooms": _number(row.get("rooms")),
        "asking_price_aed": _number(row.get("asking_price_aed")),
        "area_sqft": _number(row.get("area_sqft")),
        "developer": row.get("developer"),
        "address": row.get("address"),
        "community": row.get("community"),
        "categories": list(row.get("categories") or []),
        "amenities": list(row.get("amenities") or []),
        "views": list(row.get("views") or []),
        "text_match": None if row.get("text_match") is None else bool(row.get("text_match")),
    }
    kept = {key: value for key, value in fact.items() if value not in (None, "", [])}
    kept["place_links"] = links
    kept["verified_agent"] = bool(row.get("verified_agent"))
    kept["matches_filters"] = bool(row.get("matches_filters"))
    return kept


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)
