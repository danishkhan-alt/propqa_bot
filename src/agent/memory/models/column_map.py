"""Logical columns, filter keys, preference slots, and domain whitelists.

`properties.price` is a property/market fact. An RTA question must not inherit it.
Slots and filter keys live here so consolidate / extract / personalize share one map.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.schemas.routes import DomainRoute, as_domain_route


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    logical_col: str
    physical_col: str
    domain: str
    value_type: str
    filter_key: str | None = None
    slot: str | None = None
    exclusive: bool = False


SEED: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        "properties.bedrooms",
        "properties.bedrooms",
        "property_search",
        "int",
        filter_key="bedrooms",
        slot="bedrooms",
        exclusive=False,
    ),
    ColumnSpec(
        "properties.location_id_v2",
        "properties.location_id_v2",
        "property_search",
        "id_list",
        filter_key="location_id_v2",
        slot="preferred_location",
        exclusive=True,
    ),
    ColumnSpec(
        "properties.price",
        "properties.price",
        "property_search",
        "numeric",
        filter_key="price",
        slot="budget_max",
        exclusive=True,
    ),
    ColumnSpec(
        "properties.metro_distance_m",
        "properties.metro_distance_m",
        "property_search",
        "int",
        filter_key="metro_distance_m",
        slot="proximity_metro",
        exclusive=True,
    ),
    ColumnSpec(
        "properties.purpose",
        "properties.purpose",
        "property_search",
        "text",
        filter_key="purpose",
        slot="purpose",
        exclusive=True,
    ),
    ColumnSpec(
        "properties.is_furnished",
        "properties.is_furnished",
        "property_search",
        "bool",
        filter_key="is_furnished",
        slot="furnished",
        exclusive=True,
    ),
)

# Slots with no warehouse column (persona / goal / projection prefs).
NON_COLUMN_EXCLUSIVE_SLOTS = frozenset({"persona", "projection_pref", "active_goal"})

# A column's owner is one domain. Several domains may still inject it.
DOMAIN_COLUMNS: dict[str, frozenset[str]] = {
    "property_search": frozenset(spec.logical_col for spec in SEED),
    "market_intel": frozenset(
        {"properties.price", "properties.purpose", "properties.location_id_v2"}
    ),
    "location_intel": frozenset({"properties.location_id_v2"}),
    "communities_intel": frozenset(
        {"properties.location_id_v2", "properties.metro_distance_m"}
    ),
    "offplan_projects": frozenset({"properties.location_id_v2"}),
    "rta_intel": frozenset({"properties.location_id_v2"}),
}

CATALOG_TO_MEMORY: dict[str, str] = {
    "listings": "property_search",
    "agencies": "property_search",
    "transactions": "market_intel",
    "market": "market_intel",
    "locations": "location_intel",
    "amenities": "communities_intel",
    "schools": "communities_intel",
    "regulations": "communities_intel",
    "developers": "offplan_projects",
    "rta": "rta_intel",
}

FILTER_COLUMNS = {
    spec.filter_key: spec.logical_col for spec in SEED if spec.filter_key
}

EXCLUSIVE_SLOTS = frozenset(
    {spec.slot for spec in SEED if spec.slot and spec.exclusive} | NON_COLUMN_EXCLUSIVE_SLOTS
)

PROJECTION_DOMAINS = frozenset({"property_search", "market_intel"})


def seed_map() -> dict[str, ColumnSpec]:
    return {spec.logical_col: spec for spec in SEED}


def slot_for_filter_key(
    filter_key: str, columns: dict[str, ColumnSpec] | None = None
) -> str | None:
    """Map a QueryFrame predicate key (e.g. price) to its preference slot (budget_max)."""
    for spec in (columns or seed_map()).values():
        if spec.filter_key == filter_key:
            return spec.slot
    return None


def logical_for_filter_key(
    filter_key: str, columns: dict[str, ColumnSpec] | None = None
) -> str | None:
    """Map a QueryFrame predicate key to the logical column name."""
    for spec in (columns or seed_map()).values():
        if spec.filter_key == filter_key:
            return spec.logical_col
    return FILTER_COLUMNS.get(filter_key)


def columns_for_domains(domains: list[str] | set[str]) -> frozenset[str]:
    allowed: set[str] = set()
    for domain in domains:
        allowed.update(DOMAIN_COLUMNS.get(domain, ()))
    return frozenset(allowed)


def memory_domains_for(domain_route: DomainRoute | dict | None) -> list[str]:
    route = as_domain_route(domain_route)
    if route is None:
        return []
    found: list[str] = []
    for domain_id in [*route.domain_ids, *route.join_ids]:
        mapped = CATALOG_TO_MEMORY.get(domain_id)
        if mapped and mapped not in found:
            found.append(mapped)
    return found


def resolve_column(logical: str, columns: dict[str, ColumnSpec] | None = None) -> str:
    table = columns if columns is not None else seed_map()
    spec = table.get(logical)
    return spec.physical_col if spec else logical
