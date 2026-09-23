"""Logical columns and which routed domain is allowed to see them.

`properties.price` is a property/market fact. An RTA question must not inherit it.
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


SEED: tuple[ColumnSpec, ...] = (
    ColumnSpec("properties.bedrooms", "properties.bedrooms", "property_search", "int"),
    ColumnSpec("properties.location_id_v2", "properties.location_id_v2", "property_search", "id_list"),
    ColumnSpec("properties.price", "properties.price", "property_search", "numeric"),
    ColumnSpec("properties.metro_distance_m", "properties.metro_distance_m", "property_search", "int"),
    ColumnSpec("properties.purpose", "properties.purpose", "property_search", "text"),
    ColumnSpec("properties.is_furnished", "properties.is_furnished", "property_search", "bool"),
)

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

# One active value. A new explicit statement replaces the old one.
EXCLUSIVE_SLOTS = frozenset(
    {
        "purpose",
        "persona",
        "preferred_location",
        "budget_max",
        "furnished",
        "projection_pref",
        "active_goal",
        "proximity_metro",
    }
)

FILTER_COLUMNS = {
    "bedrooms": "properties.bedrooms",
    "price": "properties.price",
    "location_id_v2": "properties.location_id_v2",
    "purpose": "properties.purpose",
    "is_furnished": "properties.is_furnished",
    "metro_distance_m": "properties.metro_distance_m",
}

PROJECTION_DOMAINS = frozenset({"property_search", "market_intel"})


def seed_map() -> dict[str, ColumnSpec]:
    return {spec.logical_col: spec for spec in SEED}


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
