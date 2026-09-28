"""Search live listings from typed filters. The model fills the filters; this module writes the SQL.

A place matches a listing in any of the ways a listing can point at it: its v2 location, one
of its three legacy location ids, or a part of its address, because many listings carry only
the address. When nothing matches, filters are loosened in a fixed order and every step is
reported, so the reply can say what was relaxed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import lru_cache
from typing import Any

from agent.enums.listing import Completion, Furnishing, ListingPurpose, ListingSort, NearStation
from agent.grounding.name_matching import normalize_name
from agent.schemas.listing_search import ListingQuery, ListingResult, ListingSearch, Relaxation
from agent.sql.listing_sql_fragments import ACTIVE_LISTING_CONDITION, ASKING_PRICE_SQL
from agent.sql.transit import near_station_clause
from catalog import load_domain

_ORDER_BY = {
    ListingSort.NEWEST: "p.created_at DESC NULLS LAST",
    ListingSort.PRICE_LOW: f"{ASKING_PRICE_SQL} ASC NULLS LAST",
    ListingSort.PRICE_HIGH: f"{ASKING_PRICE_SQL} DESC NULLS LAST",
    ListingSort.SIZE_LARGE: "p.area DESC NULLS LAST",
}
# Stored value of properties.purpose for each purpose the router can choose.
_STORED_PURPOSE = {ListingPurpose.SALE: "for_sale", ListingPurpose.RENT: "for_rent"}

ListingRunner = Callable[[str, dict[str, Any]], Any]
WIDER_STATION_KM = 2.0


RELAXATIONS: tuple[Relaxation, ...] = (
    Relaxation(
        note="No listing matched the price range, so these results ignore price.",
        applies=lambda f: f.price_min is not None or f.price_max is not None,
        relax=lambda f: f.model_copy(update={"price_min": None, "price_max": None}),
    ),
    Relaxation(
        note="No listing matched the size range, so these results ignore size.",
        applies=lambda f: f.size_min_sqft is not None or f.size_max_sqft is not None,
        relax=lambda f: f.model_copy(update={"size_min_sqft": None, "size_max_sqft": None}),
    ),
    Relaxation(
        note="No listing had that bedroom count, so one bedroom either way is included.",
        applies=lambda f: f.bedrooms_min is not None or f.bedrooms_max is not None,
        relax=lambda f: f.model_copy(
            update={
                "bedrooms_min": None if f.bedrooms_min is None else max(0, f.bedrooms_min - 1),
                "bedrooms_max": None if f.bedrooms_max is None else f.bedrooms_max + 1,
            }
        ),
    ),
    Relaxation(
        note="No listing matched the furnishing, so these results include any furnishing.",
        applies=lambda f: f.furnishing is not Furnishing.ANY,
        relax=lambda f: f.model_copy(update={"furnishing": Furnishing.ANY}),
    ),
    Relaxation(
        note="No listing matched the completion status, so ready and off-plan are both included.",
        applies=lambda f: f.completion is not Completion.ANY,
        relax=lambda f: f.model_copy(update={"completion": Completion.ANY}),
    ),
    # Being near a station is the point of such a search, so it is widened before it is dropped.
    Relaxation(
        note=f"No listing was that close to a station, so this widens the walk to {WIDER_STATION_KM:g} km.",
        applies=lambda f: f.near_station is not NearStation.ANY and f.station_km < WIDER_STATION_KM,
        relax=lambda f: f.model_copy(update={"station_within_km": WIDER_STATION_KM}),
    ),
    Relaxation(
        note="No listing was near a station, so these results ignore the distance to one.",
        applies=lambda f: f.near_station is not NearStation.ANY,
        relax=lambda f: f.model_copy(update={"near_station": NearStation.ANY, "station_within_km": 0}),
    ),
)


def resolve_category_ids(property_types: list[str]) -> tuple[list[int], list[str]]:
    """Category ids for the types named, and the types no category matched."""
    by_name = _categories_by_name()
    ids: list[int] = []
    unknown: list[str] = []
    for text in property_types:
        category = by_name.get(_singularize(text))
        if category is None:
            unknown.append(text)
        elif category not in ids:
            ids.append(category)
    return ids, unknown


def property_type_names() -> list[str]:
    """Property type names the router chooses from, read from the catalog."""
    return sorted(set(_category_display_names()))


def build_listing_query(search: ListingSearch, *, limit: int, offset: int) -> ListingQuery:
    clauses = [ACTIVE_LISTING_CONDITION]
    params: dict[str, Any] = {}
    filters = search.filters

    if filters.purpose is not ListingPurpose.ANY:
        clauses.append("p.purpose = %(purpose)s")
        params["purpose"] = _STORED_PURPOSE[filters.purpose]
    categories, _ = resolve_category_ids(filters.property_types)
    if categories:
        clauses.append(
            "EXISTS (SELECT 1 FROM public.category_property cp "
            "WHERE cp.property_id = p.id AND cp.category_id = ANY(%(category_ids)s))"
        )
        params["category_ids"] = categories
    _add_range_filter(clauses, params, "p.rooms", "bedrooms", filters.bedrooms_min, filters.bedrooms_max)
    _add_range_filter(clauses, params, ASKING_PRICE_SQL, "price", filters.price_min, filters.price_max)
    _add_range_filter(clauses, params, "p.area", "size", filters.size_min_sqft, filters.size_max_sqft)
    if filters.furnishing is not Furnishing.ANY:
        clauses.append("p.furnished = %(furnishing)s")
        params["furnishing"] = filters.furnishing.value
    if filters.completion is not Completion.ANY:
        clauses.append("p.completion_status = %(completion)s")
        params["completion"] = filters.completion.value
    if filters.near_station is not NearStation.ANY:
        clauses.append(near_station_clause(filters.near_station, filters.station_km, params))
    if search.developers:
        clauses.append("p.developer = ANY(%(developers)s)")
        params["developers"] = list(search.developers)
    place_clause = _place_clause(search, params)
    if place_clause:
        clauses.append(place_clause)

    where = "\n  AND ".join(clauses)
    order_by = _ORDER_BY[filters.sort]
    params.update(limit=limit, offset=offset)
    return ListingQuery(
        sql=(
            f"SELECT p.id AS property_id\nFROM public.properties p\nWHERE {where}\n"
            f"ORDER BY {order_by}, p.id DESC\nLIMIT %(limit)s OFFSET %(offset)s"
        ),
        count_sql=f"SELECT count(*) AS total\nFROM public.properties p\nWHERE {where}",
        params=params,
    )


def search_listings(search: ListingSearch, run: ListingRunner, *, limit: int, offset: int) -> ListingResult:
    """Count, loosen in order while nothing matches, then fetch one page of ids."""
    notes: list[str] = []
    current = search
    query = build_listing_query(current, limit=limit, offset=offset)
    total, duration_ms = _count_matching_listings(query, run)
    for relaxation in RELAXATIONS:
        if total:
            break
        if not relaxation.applies(current.filters):
            continue
        current = replace(current, filters=relaxation.relax(current.filters))
        query = build_listing_query(current, limit=limit, offset=offset)
        total, elapsed = _count_matching_listings(query, run)
        duration_ms += elapsed
        notes.append(relaxation.note)
    if not total:
        return ListingResult(
            ids=[], total=0, query=query, notes=notes, duration_ms=duration_ms, filters=current.filters
        )
    page = run(query.sql, query.params)
    ids = [str(row["property_id"]) for row in page.rows if row.get("property_id") is not None]
    return ListingResult(
        ids=ids,
        total=total,
        query=query,
        notes=notes,
        duration_ms=duration_ms + int(getattr(page, "duration_ms", 0) or 0),
        filters=current.filters,
    )


def _count_matching_listings(query: ListingQuery, run: ListingRunner) -> tuple[int, int]:
    page = run(query.count_sql, query.params)
    rows = list(getattr(page, "rows", []) or [])
    total = int(rows[0].get("total") or 0) if rows else 0
    return total, int(getattr(page, "duration_ms", 0) or 0)


def _add_range_filter(
    clauses: list[str],
    params: dict[str, Any],
    expression: str,
    name: str,
    low: float | None,
    high: float | None,
) -> None:
    if low is not None:
        clauses.append(f"{expression} >= %({name}_min)s")
        params[f"{name}_min"] = low
    if high is not None:
        clauses.append(f"{expression} <= %({name}_max)s")
        params[f"{name}_max"] = high


def _place_clause(search: ListingSearch, params: dict[str, Any]) -> str:
    links: list[str] = []
    v2_ids = sorted({node_id for place in search.places for node_id in place.v2_ids})
    legacy_ids = sorted({node_id for place in search.places for node_id in place.legacy_ids})
    address_names = sorted({name for place in search.places for name in place.address_names})
    if v2_ids:
        links.append("p.location_v2_id = ANY(%(place_v2_ids)s)")
        params["place_v2_ids"] = v2_ids
    if legacy_ids:
        links.extend(
            f"p.{column} = ANY(%(place_legacy_ids)s)"
            for column in ("location_master_project_id", "location_project_id", "location_building_id")
        )
        params["place_legacy_ids"] = legacy_ids
    if address_names:
        links.append(
            "EXISTS (SELECT 1 FROM unnest(string_to_array(lower(p.address_en), ',')) AS part "
            "WHERE trim(part) = ANY(%(place_address_names)s))"
        )
        params["place_address_names"] = address_names
    if search.unmatched_places:
        links.append("p.address_en ILIKE ANY(%(place_address_patterns)s)")
        params["place_address_patterns"] = [f"%{_escape_like_pattern(text)}%" for text in search.unmatched_places]
    return f"({' OR '.join(links)})" if links else ""


def _escape_like_pattern(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@lru_cache(maxsize=1)
def _categories_by_name() -> dict[str, int]:
    """Singular name and slug of every PropertyCategory in the listings catalog, to its id."""
    by_name: dict[str, int] = {}
    for value in _property_categories():
        for text in (value.get("name"), value.get("slug")):
            if text:
                by_name[_singularize(str(text))] = int(value["id"])
    return by_name


def _category_display_names() -> list[str]:
    return [str(value["name"]).lower() for value in _property_categories() if value.get("name")]


@lru_cache(maxsize=1)
def _property_categories() -> tuple[dict, ...]:
    enums = load_domain("listings").get("enums") or []
    values = next((enum.get("values") or [] for enum in enums if enum.get("name") == "PropertyCategory"), [])
    return tuple(values)


def _singularize(text: str) -> str:
    words = normalize_name(text).split()
    return " ".join(word[:-1] if len(word) > 3 and word.endswith("s") else word for word in words)
