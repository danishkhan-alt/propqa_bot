"""A listing search built from the router's filters, the SQL it runs, and what came back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.schemas.grounding import GroundedFeature, GroundedPlace
from agent.schemas.listing import ListingFilters


@dataclass(frozen=True)
class BrandPlace:
    """A name that is both a place and a developer. The listing may match either."""

    place: GroundedPlace
    developers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ListingSearch:
    filters: ListingFilters
    places: list[GroundedPlace] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)
    # Developer names nothing stored exactly. Matched with ILIKE on the brand, never dropped.
    developer_patterns: list[str] = field(default_factory=list)
    # Place names nothing matched. Searched as address text so they are not silently dropped.
    unmatched_places: list[str] = field(default_factory=list)
    agency_ids: list[int] = field(default_factory=list)
    agency_names: list[str] = field(default_factory=list)
    agency_patterns: list[str] = field(default_factory=list)
    agent_ids: list[int] = field(default_factory=list)
    agent_names: list[str] = field(default_factory=list)
    agent_patterns: list[str] = field(default_factory=list)
    brand_places: list[BrandPlace] = field(default_factory=list)
    # Requirements that name stored amenities or views. A listing needs one of each group's
    # features, and every group, or any group when `any_feature`.
    features: list[GroundedFeature] = field(default_factory=list)
    any_feature: bool = False
    # Requirements no stored amenity or view names. When listing text search is on, these
    # are matched against the listing title and description. Otherwise the search cannot
    # check them and says so.
    unchecked_requirements: list[str] = field(default_factory=list)
    # Unresolved requirements that listing text search will match, in the user's words.
    text_requirements: list[str] = field(default_factory=list)
    # Bound websearch string for public.properties.search_vector. None skips that match.
    text_query: str | None = None
    # A catalog amenity or view also matches when the listing text names it.
    match_features_in_text: bool = False


@dataclass(frozen=True)
class ListingQuery:
    sql: str
    count_sql: str
    params: dict[str, Any]


@dataclass(frozen=True)
class ListingResult:
    ids: list[str]
    total: int
    query: ListingQuery
    notes: list[str]
    duration_ms: int
    # The filters the ids were found with, after any loosening.
    filters: ListingFilters = field(default_factory=ListingFilters)


@dataclass(frozen=True)
class Relaxation:
    """One way to loosen a search that matched nothing."""

    note: str
    applies: Callable[[ListingFilters], bool]
    relax: Callable[[ListingFilters], ListingFilters]
