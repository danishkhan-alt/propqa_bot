"""Search live listings from typed filters. The model fills the filters; this module writes the SQL.

A place matches a listing in any of the ways a listing can point at it: its v2 location, one
of its three legacy location ids, or a part of its address, because many listings carry only
the address. When nothing matches, filters are loosened in a fixed order and every step is
reported, so the reply can say what was relaxed.

A requirement that names a stored amenity or view is filtered on that tag. The same
requirement can also match the listing's own text. Anything the catalog does not name
("high ceilings") is a required match on that text, and is never dropped so the search
falls through to every listing of that type.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import lru_cache
from typing import Any

from agent.enums.listing import Completion, Furnishing, ListingPurpose, ListingSort, NearStation
from agent.grounding.name_matching import brand_stem, normalize_name
from agent.schemas.listing import GOLDEN_VISA_MIN_PRICE_AED
from agent.schemas.listing_search import ListingQuery, ListingResult, ListingSearch, Relaxation
from agent.sql.listing_sql_fragments import (
    ACTIVE_LISTING_CONDITION,
    ASKING_PRICE_SQL,
    TEXT_SEARCH_CONDITION,
    TEXT_SEARCH_RANK,
    VERIFIED_AGENT_CONDITION,
)
from agent.sql.listing_text_search import broaden_with_synonyms, build_text_query
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
UNCHECKED_REQUIREMENT_NOTE = "The search could not check {requirement}, so these results may not have it."
DROPPED_FEATURES_NOTE = "None of the otherwise matching listings has {features}, so these results ignore that."
TEXT_SYNONYMS_NOTE = "No listing matched {text} exactly, so similar wording is included."
TYPE_FAMILY_NOTE = "No {asked} mention {text}, so {added} are included."
OTHER_TYPES_NOTE = "No {asked} mention {text}; these {count} other listings do."
# Villa and villa compound are the same kind of home for a description search. Apartments are not.
_VILLA_FAMILY = ("villa", "villa compound")


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
    if filters.golden_visa:
        # Eligibility, not a preference: no relaxation removes it.
        clauses.append(f"{ASKING_PRICE_SQL} >= %(golden_visa_min)s")
        params["golden_visa_min"] = GOLDEN_VISA_MIN_PRICE_AED
    _add_range_filter(clauses, params, "p.area", "size", filters.size_min_sqft, filters.size_max_sqft)
    if filters.furnishing is not Furnishing.ANY:
        clauses.append("p.furnished = %(furnishing)s")
        params["furnishing"] = filters.furnishing.value
    if filters.completion is not Completion.ANY:
        clauses.append("p.completion_status = %(completion)s")
        params["completion"] = filters.completion.value
    if filters.near_station is not NearStation.ANY:
        clauses.append(near_station_clause(filters.near_station, filters.station_km, params))
    developer_clause = _developer_clause(search, params)
    if developer_clause:
        clauses.append(developer_clause)
    agency_clause = _agency_clause(search, params)
    if agency_clause:
        clauses.append(agency_clause)
    agent_clause = _agent_clause(search, params)
    if agent_clause:
        clauses.append(agent_clause)
    if filters.verified_agent:
        clauses.append(VERIFIED_AGENT_CONDITION)
    feature_clause = _feature_clause(search, params)
    if feature_clause:
        clauses.append(feature_clause)
    place_clause = _place_clause(search, params)
    if place_clause:
        clauses.append(place_clause)
    for index, brand in enumerate(search.brand_places):
        brand_clause = _brand_clause(brand, index, params)
        if brand_clause:
            clauses.append(brand_clause)
    if search.text_query:
        clauses.append(TEXT_SEARCH_CONDITION.format(param="text_query"))
        params["text_query"] = search.text_query

    where = "\n  AND ".join(clauses)
    order_by = _ORDER_BY[filters.sort]
    if search.text_query and filters.sort is ListingSort.NEWEST:
        order_by = f"{TEXT_SEARCH_RANK.format(param='text_query')} DESC, {order_by}"
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
    notes = [UNCHECKED_REQUIREMENT_NOTE.format(requirement=text) for text in search.unchecked_requirements]
    current = search
    query = build_listing_query(current, limit=limit, offset=offset)
    total, duration_ms = _count_matching_listings(query, run)
    if not total and current.text_query:
        current, query, total, elapsed = _recover_listing_text(current, run, notes, limit=limit, offset=offset)
        duration_ms += elapsed
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
    # The features the user asked for go last: they are often the point of the search.
    if not total and current.features:
        joiner = " or " if current.any_feature else " and "
        notes.append(DROPPED_FEATURES_NOTE.format(features=joiner.join(f.text for f in current.features)))
        current = replace(current, features=[])
        query = build_listing_query(current, limit=limit, offset=offset)
        total, elapsed = _count_matching_listings(query, run)
        duration_ms += elapsed
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


def _recover_listing_text(
    search: ListingSearch,
    run: ListingRunner,
    notes: list[str],
    *,
    limit: int,
    offset: int,
) -> tuple[ListingSearch, ListingQuery, int, int]:
    """Loosen a description match that found nothing. The text match itself stays required.

    Similar wording, then villa with villa compound, then other property types when those
    mention it. Price and bedroom loosening happens later and still keeps the text match.
    """
    current = search
    query = build_listing_query(current, limit=limit, offset=offset)
    total = 0
    elapsed = 0
    mentioned = _mentioned_text(search)

    broadened = broaden_with_synonyms(current.text_requirements)
    if broadened and broadened != current.text_query:
        current = replace(current, text_query=broadened)
        notes.append(TEXT_SYNONYMS_NOTE.format(text=mentioned))
        query = build_listing_query(current, limit=limit, offset=offset)
        total, step = _count_matching_listings(query, run)
        elapsed += step
        if total:
            return current, query, total, elapsed

    widened = _villa_family_types(current.filters.property_types)
    if widened is not None:
        added = [name for name in widened if name not in current.filters.property_types]
        notes.append(
            TYPE_FAMILY_NOTE.format(
                asked=_type_phrase(current.filters.property_types),
                added=_type_phrase(added),
                text=mentioned,
            )
        )
        current = replace(current, filters=current.filters.model_copy(update={"property_types": widened}))
        query = build_listing_query(current, limit=limit, offset=offset)
        total, step = _count_matching_listings(query, run)
        elapsed += step
        if total:
            return current, query, total, elapsed

    if current.filters.property_types:
        loosened = replace(current, filters=current.filters.model_copy(update={"property_types": []}))
        other_query = build_listing_query(loosened, limit=limit, offset=offset)
        other_total, step = _count_matching_listings(other_query, run)
        elapsed += step
        if other_total:
            notes.append(
                OTHER_TYPES_NOTE.format(
                    asked=_type_phrase(current.filters.property_types),
                    text=mentioned,
                    count=other_total,
                )
            )
            return loosened, other_query, other_total, elapsed

    return current, query, total, elapsed


def _mentioned_text(search: ListingSearch) -> str:
    if search.text_requirements:
        return " and ".join(search.text_requirements)
    return search.text_query or "that description"


def _villa_family_types(property_types: list[str]) -> list[str] | None:
    """The user's villa types plus the other villa type, or None when that widen does not apply."""
    if not property_types:
        return None
    family_ids, unknown_family = resolve_category_ids(list(_VILLA_FAMILY))
    if unknown_family or len(set(family_ids)) < 2:
        return None
    current_ids, unknown = resolve_category_ids(property_types)
    if unknown or not current_ids:
        return None
    family = set(family_ids)
    current = set(current_ids)
    if not current <= family or current == family:
        return None
    name_by_id = dict(zip(family_ids, _VILLA_FAMILY, strict=True))
    missing = [name_by_id[category_id] for category_id in family_ids if category_id not in current]
    return [*property_types, *missing]


def _type_phrase(property_types: list[str]) -> str:
    labels = [_pluralize_type(name) for name in property_types]
    if len(labels) <= 1:
        return labels[0] if labels else "listings"
    if len(labels) == 2:
        return f"{labels[0]} or {labels[1]}"
    return ", ".join(labels[:-1]) + f", or {labels[-1]}"


def _pluralize_type(name: str) -> str:
    words = name.split()
    if not words or words[-1].endswith("s"):
        return name
    words[-1] = f"{words[-1]}s"
    return " ".join(words)


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


def _developer_clause(search: ListingSearch, params: dict[str, Any]) -> str:
    parts: list[str] = []
    if search.developers:
        parts.append("p.developer = ANY(%(developers)s)")
        params["developers"] = list(search.developers)
    needles = _like_needles(search.developer_patterns)
    if needles:
        parts.append("p.developer ILIKE ANY(%(developer_patterns)s)")
        params["developer_patterns"] = needles
    return _or_group(parts)


def _agency_clause(search: ListingSearch, params: dict[str, Any]) -> str:
    parts: list[str] = []
    if search.agency_ids:
        parts.append("(p.agency_id = ANY(%(agency_ids)s) OR p.user_id = ANY(%(agency_ids)s))")
        params["agency_ids"] = list(search.agency_ids)
    needles = _like_needles(search.agency_patterns)
    if needles:
        parts.append(
            "EXISTS (SELECT 1 FROM public.users au "
            "WHERE au.deleted_at IS NULL AND (au.id = p.agency_id OR au.id = p.user_id) "
            "AND (au.company_name ILIKE ANY(%(agency_patterns)s) OR au.name_en ILIKE ANY(%(agency_patterns)s)))"
        )
        params["agency_patterns"] = needles
    return _or_group(parts)


def _agent_clause(search: ListingSearch, params: dict[str, Any]) -> str:
    parts: list[str] = []
    if search.agent_ids:
        parts.append("p.user_id = ANY(%(agent_ids)s)")
        params["agent_ids"] = list(search.agent_ids)
    needles = _like_needles(search.agent_patterns)
    if needles:
        parts.append(
            "EXISTS (SELECT 1 FROM public.users ag "
            "WHERE ag.deleted_at IS NULL AND ag.id = p.user_id AND ag.name_en ILIKE ANY(%(agent_patterns)s))"
        )
        params["agent_patterns"] = needles
    return _or_group(parts)


def _brand_clause(brand, index: int, params: dict[str, Any]) -> str:
    place_sql = _places_sql([brand.place], [], params, f"brand_{index}")
    if not brand.developers:
        return place_sql
    key = f"brand_{index}_developers"
    developer_sql = f"p.developer = ANY(%({key})s)"
    params[key] = list(brand.developers)
    if not place_sql:
        return developer_sql
    return f"({place_sql} OR {developer_sql})"


def _place_clause(search: ListingSearch, params: dict[str, Any]) -> str:
    return _places_sql(search.places, search.unmatched_places, params, "place")


def _places_sql(places, unmatched: list[str], params: dict[str, Any], prefix: str) -> str:
    links: list[str] = []
    v2_ids = sorted({node_id for place in places for node_id in place.v2_ids})
    legacy_ids = sorted({node_id for place in places for node_id in place.legacy_ids})
    address_names = sorted({name for place in places for name in place.address_names})
    if v2_ids:
        key = f"{prefix}_v2_ids"
        links.append(f"p.location_v2_id = ANY(%({key})s)")
        params[key] = v2_ids
    if legacy_ids:
        key = f"{prefix}_legacy_ids"
        links.extend(
            f"p.{column} = ANY(%({key})s)"
            for column in ("location_master_project_id", "location_project_id", "location_building_id")
        )
        params[key] = legacy_ids
    if address_names:
        key = f"{prefix}_address_names"
        links.append(
            "EXISTS (SELECT 1 FROM unnest(string_to_array(lower(p.address_en), ',')) AS part "
            f"WHERE trim(part) = ANY(%({key})s))"
        )
        params[key] = address_names
    if unmatched:
        key = f"{prefix}_address_patterns"
        links.append(f"p.address_en ILIKE ANY(%({key})s)")
        params[key] = [f"%{_escape_like_pattern(text)}%" for text in unmatched]
    return _or_group(links)


def _or_group(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"({' OR '.join(parts)})"


def _like_needles(texts: list[str]) -> list[str]:
    needles: list[str] = []
    for text in texts:
        needle = brand_stem(text) or normalize_name(text)
        if needle and needle not in needles:
            needles.append(f"%{_escape_like_pattern(needle)}%")
    return needles


def _feature_clause(search: ListingSearch, params: dict[str, Any]) -> str:
    """A listing has one of each requirement's amenities or views; all requirements, or any."""
    groups: list[str] = []
    for index, feature in enumerate(search.features):
        links: list[str] = []
        if feature.amenity_ids:
            links.append(
                "EXISTS (SELECT 1 FROM public.amenity_property ap "
                f"WHERE ap.property_id = p.id AND ap.amenity_id = ANY(%(feature_{index}_amenity_ids)s))"
            )
            params[f"feature_{index}_amenity_ids"] = list(feature.amenity_ids)
        if feature.view_ids:
            links.append(
                "EXISTS (SELECT 1 FROM public.property_view pv "
                f"WHERE pv.property_id = p.id AND pv.view_id = ANY(%(feature_{index}_view_ids)s))"
            )
            params[f"feature_{index}_view_ids"] = list(feature.view_ids)
        if search.match_features_in_text:
            quoted = build_text_query([feature.text])
            if quoted:
                links.append(TEXT_SEARCH_CONDITION.format(param=f"feature_{index}_text"))
                params[f"feature_{index}_text"] = quoted
        if links:
            groups.append(f"({' OR '.join(links)})")
    if not groups:
        return ""
    return f"({(' OR ' if search.any_feature else ' AND ').join(groups)})"


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
