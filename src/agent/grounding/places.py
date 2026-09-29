"""Places people search by, built from both location trees and listing addresses.

A listing can point at a place in three ways: `location_v2_id` (the v2 tree), the three
legacy `location_*_id` columns (the legacy tree), or only its `address_en` text. A place
therefore carries every id under it in both trees and the names its address parts use.
Nodes from either tree that share a name are one place.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Mapping

from agent.enums.grounding import Breadth, MatchTier
from agent.grounding.name_matching import (
    NameMatcher,
    name_variants,
    normalize_name,
    without_brackets,
)
from agent.schemas.grounding_index import (
    ListingCountsByPlaceLink,
    LocationNode,
    NameHit,
    Place,
    PlaceMatch,
)

MAX_ALTERNATIVES = 3
# Most stations and stops are named after the place they serve: "Business Bay Metro Station"
# is in Business Bay. Longest first, so "metro station" is removed whole.
TRANSIT_SUFFIXES = ("metro station", "bus station", "tram station", "bus stop", "tram stop", "station", "metro", "stop")
# A place covers a place whose name extends its own ("Dubai Hills" and "Dubai Hills Estate",
# "DUBAI HILLS - SIDRA 1") when the two are at most this far apart.
COVER_RADIUS_KM = 1.5
# Nodes of the two trees with the same name this close together are one location.
SAME_SPOT_RADIUS_KM = 1.0
_EARTH_RADIUS_KM = 6371.0


V2_BREADTH = {
    "country": Breadth.REGION,
    "emirate": Breadth.REGION,
    "province": Breadth.REGION,
    "district": Breadth.AREA,
    "sub district": Breadth.AREA,
    "neighbourhood": Breadth.AREA,
    "cluster": Breadth.PROJECT,
    "building": Breadth.BUILDING,
}
LEGACY_BREADTH = {
    "master_project": Breadth.AREA,
    "project": Breadth.PROJECT,
    "building": Breadth.BUILDING,
}
_PLACE_BREADTHS = frozenset({Breadth.AREA, Breadth.PROJECT})


class PlaceDirectory:
    def __init__(
        self,
        places: Iterable[Place],
        region: str = "",
        aliases: Mapping[str, list[str]] | None = None,
    ) -> None:
        self._places = {place.key: place for place in places}
        self._region = normalize_name(region)
        self._matcher: NameMatcher[str] = NameMatcher()
        for place in self._places.values():
            self._matcher.add(place.key, place.names)
        for wording, stored_names in (aliases or {}).items():
            for stored in stored_names:
                key = _place_key(stored)
                if key in self._places:
                    self._matcher.add(key, [wording])

    def __len__(self) -> int:
        return len(self._places)

    def find(self, phrase: str) -> PlaceMatch | None:
        """The place a phrase most likely means. None for the whole region or no match."""
        if not normalize_name(phrase) or normalize_name(phrase) == self._region:
            return None
        hits = self._matcher.find(phrase)
        if not hits:
            return self._place_a_station_is_named_after(phrase)
        if hits[0].tier is MatchTier.WORDS:
            # "palm jumeriah" is spelled inside a tower's stored name, but it misspells the
            # whole name of the island. The broader place it misspells is what was meant.
            typos = self._matcher.find_typos(phrase)
            if typos and min(self._breadth(hit) for hit in typos) < min(self._breadth(hit) for hit in hits):
                hits = typos
        ranked = sorted(hits, key=self._rank)
        best = self._places[ranked[0].key]
        alternatives = tuple(self._places[hit.key].title for hit in ranked[1 : 1 + MAX_ALTERNATIVES])
        return PlaceMatch(place=best, tier=ranked[0].tier, alternatives=alternatives)

    def _place_a_station_is_named_after(self, phrase: str) -> PlaceMatch | None:
        """The place in a station's name, as an approximate reading: the station is in it."""
        normalized = normalize_name(phrase)
        for suffix in TRANSIT_SUFFIXES:
            if normalized.endswith(f" {suffix}"):
                match = self.find(normalized.removesuffix(f" {suffix}"))
                if match is None:
                    return None
                return PlaceMatch(place=match.place, tier=MatchTier.FUZZY, alternatives=match.alternatives)
        return None

    def _breadth(self, hit: NameHit[str]) -> Breadth:
        return self._places[hit.key].breadth

    def _rank(self, hit: NameHit[str]) -> tuple:
        place = self._places[hit.key]
        if hit.tier is MatchTier.FUZZY:
            # A typo: the closest spelling matters more than how broad the place is.
            return (-hit.coverage, place.breadth, -place.listing_count, place.title)
        return (place.breadth, -hit.coverage, -place.listing_count, place.title)


def build_place_directory(
    v2_nodes: Iterable[LocationNode],
    legacy_nodes: Iterable[LocationNode],
    links: ListingCountsByPlaceLink,
    *,
    region: str,
    aliases: Mapping[str, list[str]] | None = None,
    inside_outline: Mapping[int, Iterable[int]] | None = None,
) -> PlaceDirectory:
    """Group both trees into places. v2 is limited to the region; legacy is the product's own tree.

    `inside_outline` maps a v2 area with a drawn outline to the legacy nodes whose point lies in it.
    """
    v2 = nodes_in_region({node.id: node for node in v2_nodes}, region)
    legacy = {node.id: node for node in legacy_nodes}
    places: dict[str, Place] = {}
    for tree, is_v2 in ((v2, True), (legacy, False)):
        descendants = _subtree_ids_by_node(tree)
        for node in tree.values():
            key = _place_key(node.title)
            if not key or node.breadth is Breadth.REGION:
                continue
            place = places.get(key)
            if place is None:
                place = places[key] = Place(
                    key=key, title=node.title, breadth=node.breadth, lat=node.lat, lng=node.lng
                )
            elif node.breadth < place.breadth:
                # v2 is read first, so its spelling is kept unless legacy has a broader node.
                place.title, place.breadth, place.lat, place.lng = node.title, node.breadth, node.lat, node.lng
            subtree = descendants[node.id]
            (place.v2_ids if is_v2 else place.legacy_ids).update(subtree)
            place.names.update(_address_spellings(node))
    for place in places.values():
        place.address_names.update(place.names)
    _cover_legacy_nodes_inside(places, v2, legacy, inside_outline or {})
    _cover_nearby_extensions(places)
    for place in places.values():
        place.listing_count = (
            sum(links.by_v2_id.get(node_id, 0) for node_id in place.v2_ids)
            + sum(links.by_legacy_id.get(node_id, 0) for node_id in place.legacy_ids)
            + sum(links.by_address_part.get(name, 0) for name in place.address_names)
        )
    return PlaceDirectory(places.values(), region=region, aliases=aliases)


def _place_key(title: str) -> str:
    return normalize_name(without_brackets(title)) or normalize_name(title)


def _cover_legacy_nodes_inside(
    places: dict[str, Place],
    v2: Mapping[int, LocationNode],
    legacy: Mapping[int, LocationNode],
    inside_outline: Mapping[int, Iterable[int]],
) -> None:
    """The v2 tree decides what lies inside a place; legacy nodes follow it.

    A legacy node belongs to a place when it is the same location as a v2 node under that
    place (same name, same spot: the legacy "Burj Khalifa" project sits under v2 "Downtown
    Dubai"), or when its point lies inside the place's drawn outline.

    Coordinates fill gaps in the trees and never override them, so an outline only places a
    legacy node that has no legacy parent and that v2 does not name as an area or project.
    The legacy "Dubai Harbour" point falls inside the Dubai Marina outline, but v2 has Dubai
    Harbour as its own area; a project filed under Palm Jumeirah stays there whatever its point says.
    """
    legacy_below = _subtree_ids_by_node(legacy)
    legacy_by_key: dict[str, list[LocationNode]] = defaultdict(list)
    for node in legacy.values():
        legacy_by_key[_place_key(node.title)].append(node)
    linked: dict[int, set[int]] = defaultdict(set)
    for node in v2.values():
        for twin in legacy_by_key.get(_place_key(node.title), ()):
            if _distance_km(node, twin) <= SAME_SPOT_RADIUS_KM:
                linked[node.id] |= legacy_below[twin.id]
    placed_by_v2 = {_place_key(node.title) for node in v2.values() if node.breadth in _PLACE_BREADTHS}
    for v2_id, legacy_ids in inside_outline.items():
        for legacy_id in legacy_ids:
            node = legacy.get(legacy_id)
            if node is None or node.parent_id in legacy or _place_key(node.title) in placed_by_v2:
                continue
            linked[v2_id] |= legacy_below[legacy_id]
    for place in places.values():
        for v2_id in list(place.v2_ids):
            place.legacy_ids |= linked.get(v2_id, set())


def _cover_nearby_extensions(places: dict[str, Place]) -> None:
    """Let an area or project also cover nearby places whose names extend its own name.

    One direction only: "Dubai Hills" covers "Dubai Hills Estate", but a search for
    "Dubai Hills View" still means only that community.
    """
    keys = sorted(places)
    own = {
        key: (set(place.v2_ids), set(place.legacy_ids), set(place.names))
        for key, place in places.items()
    }
    for place in places.values():
        if place.breadth > Breadth.PROJECT or place.lat is None:
            continue
        prefix = f"{place.key} "
        for other_key in keys[bisect_left(keys, prefix) :]:
            if not other_key.startswith(prefix):
                break
            other = places[other_key]
            if other.breadth < place.breadth or _distance_km(place, other) > COVER_RADIUS_KM:
                continue
            v2_ids, legacy_ids, names = own[other_key]
            place.v2_ids |= v2_ids
            place.legacy_ids |= legacy_ids
            place.address_names |= names
            place.covered_names |= names


def _distance_km(first: Place | LocationNode, second: Place | LocationNode) -> float:
    if None in (first.lat, first.lng, second.lat, second.lng):
        return math.inf
    lat1, lng1, lat2, lng2 = map(math.radians, (first.lat, first.lng, second.lat, second.lng))
    half = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(half))


def _address_spellings(node: LocationNode) -> set[str]:
    """Exact lowercased spellings, as they appear between the commas of `address_en`."""
    names: set[str] = set()
    for text in (node.title, *node.aliases):
        spelled = " ".join(str(text or "").lower().split())
        if spelled:
            names.add(spelled)
            names.add(without_brackets(spelled))
    names.update(variant for text in (node.title, *node.aliases) for variant in name_variants(text))
    return {name for name in names if name}


def _subtree_ids_by_node(tree: Mapping[int, LocationNode]) -> dict[int, set[int]]:
    """Each id with every id below it, itself included."""
    children: dict[int, list[int]] = defaultdict(list)
    for node in tree.values():
        if node.parent_id is not None and node.parent_id != node.id:
            children[node.parent_id].append(node.id)
    result: dict[int, set[int]] = {}
    for root in tree:
        seen = {root}
        stack = [root]
        while stack:
            for child in children.get(stack.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        result[root] = seen
    return result


def nodes_in_region(tree: dict[int, LocationNode], region: str) -> dict[int, LocationNode]:
    wanted = normalize_name(region)
    if not wanted:
        return tree
    roots = [
        node.id
        for node in tree.values()
        if node.breadth is Breadth.REGION and normalize_name(node.title) == wanted
    ]
    if not roots:
        return tree
    descendants = _subtree_ids_by_node(tree)
    kept: set[int] = set()
    for root in roots:
        kept |= descendants[root]
    return {node_id: tree[node_id] for node_id in kept}
