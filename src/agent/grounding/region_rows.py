"""Rows of a table that lie outside the product's region, such as off-plan projects in Abu Dhabi.

A table declares `region_scope` in the catalog when it mixes emirates. A row's own location
link decides where it is. A row without one follows the rows that share its place name:
if most linked "Al Marjan Island" projects are outside Dubai, so is an unlinked one.
A place name no linked row explains stays in, so nothing is dropped on a guess.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from agent.grounding.places import nodes_in_region
from agent.schemas.grounding_index import LocationNode


@dataclass(frozen=True)
class RegionScope:
    table: str
    id_column: str
    location_column: str
    place_column: str


def ids_outside_region(
    rows: Iterable[dict], scope: RegionScope, v2_nodes: list[LocationNode], region: str
) -> frozenset[int]:
    known = {node.id for node in v2_nodes}
    inside = set(nodes_in_region({node.id: node for node in v2_nodes}, region))
    votes: dict[str, Counter] = {}
    unlinked: list[tuple[int, str]] = []
    outside: set[int] = set()
    for row in rows:
        row_id, location = row.get(scope.id_column), row.get(scope.location_column)
        place = str(row.get(scope.place_column) or "").strip().lower()
        if row_id is None:
            continue
        if location is None or int(location) not in known:
            unlinked.append((int(row_id), place))
            continue
        is_inside = int(location) in inside
        votes.setdefault(place, Counter())[is_inside] += 1
        if not is_inside:
            outside.add(int(row_id))
    for row_id, place in unlinked:
        tally = votes.get(place)
        if place and tally and tally[False] > tally[True]:
            outside.add(row_id)
    return frozenset(outside)
