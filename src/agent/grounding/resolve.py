"""Match the names in a message to places and to stored values in the loaded tables."""

from __future__ import annotations

from collections.abc import Iterable

from agent.grounding.index import GroundingIndex
from agent.grounding.places import PlaceMatch
from agent.grounding.stored_values import PLACE_GROUP, StoredValue
from agent.schemas.grounding import GroundedName, GroundedPlace, Grounding, StoredMatch
from agent.schemas.listing import MentionKind, NameMention

_GROUPS_BY_MENTION = {
    MentionKind.PLACE: {PLACE_GROUP},
    MentionKind.DEVELOPER: {"developer"},
    MentionKind.OTHER: None,
}


def ground_names(
    mentions: Iterable[NameMention],
    index: GroundingIndex,
    tables: Iterable[str],
) -> Grounding:
    allowed = set(tables)
    return Grounding(names=[_ground(mention, index, allowed) for mention in mentions])


def _ground(mention: NameMention, index: GroundingIndex, tables: set[str]) -> GroundedName:
    match = index.places.find(mention.text) if mention.kind is MentionKind.PLACE else None
    # The place's own spellings are tried with the user's wording: "downtown" becomes
    # "Downtown Dubai", which is how the other sources spell it.
    spellings = [mention.text]
    if match is not None:
        spellings = [*sorted(match.place.names | match.place.covered_names), mention.text]
    stored = index.stored.find(spellings, tables, _GROUPS_BY_MENTION[mention.kind])
    return GroundedName(
        text=mention.text,
        kind=mention.kind,
        place=_grounded_place(match) if match is not None else None,
        stored=[_stored_match(value) for value in stored],
    )


def _grounded_place(match: PlaceMatch) -> GroundedPlace:
    place = match.place
    return GroundedPlace(
        title=place.title,
        is_approximate=match.is_approximate,
        alternatives=list(match.alternatives),
        v2_ids=sorted(place.v2_ids),
        legacy_ids=sorted(place.legacy_ids),
        address_names=sorted(place.address_names),
    )


def _stored_match(value: StoredValue) -> StoredMatch:
    return StoredMatch(
        table=value.table,
        column=value.column,
        value=value.value,
        kind=value.kind,
        same_place_as=value.same_place_as,
    )
