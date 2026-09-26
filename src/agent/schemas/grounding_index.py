"""Records the grounding index is built from and returns: location rows, places, and
stored name values, with the match found for a phrase."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from agent.enums.grounding import Breadth, MatchTier

Key = TypeVar("Key", bound=Hashable)


@dataclass(frozen=True)
class NameHit(Generic[Key]):
    key: Key
    tier: MatchTier
    # Share of the stored name the phrase covers. "marina" covers half of "dubai marina".
    coverage: float


@dataclass(frozen=True)
class LocationNode:
    """One row of a location tree."""

    id: int
    parent_id: int | None
    title: str
    breadth: Breadth
    aliases: tuple[str, ...] = ()
    lat: float | None = None
    lng: float | None = None


@dataclass
class Place:
    key: str
    title: str
    breadth: Breadth
    lat: float | None = None
    lng: float | None = None
    # Spellings of this place itself. Only these are matched against what the user typed.
    names: set[str] = field(default_factory=set)
    # Spellings of nearby places it covers by name, e.g. "dubai hills estate" for "Dubai Hills".
    covered_names: set[str] = field(default_factory=set)
    # What a search for this place covers: its subtrees in both trees and the address parts
    # that name it or a place it covers, e.g. "jumeirah village circle (jvc)".
    v2_ids: set[int] = field(default_factory=set)
    legacy_ids: set[int] = field(default_factory=set)
    address_names: set[str] = field(default_factory=set)
    listing_count: int = 0


@dataclass(frozen=True)
class PlaceMatch:
    place: Place
    tier: MatchTier
    alternatives: tuple[str, ...] = ()

    @property
    def is_approximate(self) -> bool:
        return self.tier is MatchTier.FUZZY


@dataclass(frozen=True)
class ListingCountsByPlaceLink:
    """Active listing counts per way a listing points at a place. Only used to rank ties."""

    by_v2_id: Mapping[int, int] = field(default_factory=dict)
    by_legacy_id: Mapping[int, int] = field(default_factory=dict)
    by_address_part: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class NamedColumn:
    """A column whose values are names users type. Declared in the domain YAML."""

    table: str
    column: str
    kind: str
    same_place_as: str | None = None


@dataclass(frozen=True)
class StoredValue:
    table: str
    column: str
    value: str
    kind: str
    row_count: int = 0
    # Set when this value was reached from another name on the same rows.
    same_place_as: str | None = None

