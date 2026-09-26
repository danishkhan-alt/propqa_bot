"""A listing search built from the router's filters, the SQL it runs, and what came back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.schemas.grounding import GroundedPlace
from agent.schemas.listing import ListingFilters


@dataclass(frozen=True)
class ListingSearch:
    filters: ListingFilters
    places: list[GroundedPlace] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)
    # Place names nothing matched. Searched as address text so they are not silently dropped.
    unmatched_places: list[str] = field(default_factory=list)


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


@dataclass(frozen=True)
class Relaxation:
    """One way to loosen a search that matched nothing."""

    note: str
    applies: Callable[[ListingFilters], bool]
    relax: Callable[[ListingFilters], ListingFilters]
