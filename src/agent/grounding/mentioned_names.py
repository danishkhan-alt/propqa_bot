"""Match the names in a message to places and to stored values in the loaded tables."""

from __future__ import annotations

from collections.abc import Iterable

from agent.enums.listing import MentionKind
from agent.grounding.advertisers import Advertiser
from agent.grounding.index import GroundingIndex
from agent.grounding.name_matching import brand_stem, normalize_name
from agent.grounding.stored_values import PLACE_GROUP, developer_matches
from agent.schemas.grounding import GroundedName, GroundedPlace, Grounding, StoredMatch
from agent.schemas.grounding_index import PlaceMatch, StoredValue
from agent.schemas.listing import NameMention
from agent.sql.listing_sql_fragments import LISTINGS_TABLE

_NAME_GROUPS_BY_MENTION_KIND = {
    MentionKind.PLACE: {PLACE_GROUP},
    MentionKind.DEVELOPER: {"developer"},
    MentionKind.AGENCY: None,
    MentionKind.AGENT: None,
    MentionKind.OTHER: None,
}
_ENTITY_KINDS = frozenset({MentionKind.PLACE, MentionKind.OTHER, MentionKind.AGENCY, MentionKind.AGENT})


def ground_names(
    mentions: Iterable[NameMention],
    index: GroundingIndex,
    tables: Iterable[str],
) -> Grounding:
    allowed = set(tables)
    return Grounding(names=[_ground_mention(mention, index, allowed) for mention in mentions])


def _ground_mention(mention: NameMention, index: GroundingIndex, tables: set[str]) -> GroundedName:
    match = index.places.find(mention.text) if mention.kind is MentionKind.PLACE else None
    # The place's own spellings are tried with the user's wording: "downtown" becomes
    # "Downtown Dubai", which is how the other sources spell it.
    place_spellings = sorted(match.place.names | match.place.covered_names) if match is not None else []
    stored = _stored_for_mention(mention, index, tables, place_spellings)
    if mention.kind in (MentionKind.PLACE, MentionKind.OTHER) and LISTINGS_TABLE in tables:
        # Only a developer that is the same brand. "marina" must not also match every
        # developer whose name merely contains that word.
        same_brand = [
            value
            for value in developer_matches(index.stored, mention.text, {LISTINGS_TABLE})
            if _same_brand(mention.text, value.value)
        ]
        stored = _merge_stored(stored, same_brand)
    agencies, agents = _advertisers_for_mention(mention, index, match, stored)
    titles = _titles(agencies, agents)
    return GroundedName(
        text=mention.text,
        kind=mention.kind,
        place=_grounded_place(match) if match is not None else None,
        stored=[_stored_match(value) for value in stored],
        agency_ids=[advertiser.user_id for advertiser in agencies],
        agent_ids=[advertiser.user_id for advertiser in agents],
        entity_titles=titles,
    )


def _stored_for_mention(
    mention: NameMention,
    index: GroundingIndex,
    tables: set[str],
    place_spellings: list[str],
) -> list[StoredValue]:
    if mention.kind is MentionKind.DEVELOPER:
        return developer_matches(index.stored, mention.text, tables)
    groups = _NAME_GROUPS_BY_MENTION_KIND[mention.kind]
    if mention.kind in (MentionKind.AGENCY, MentionKind.AGENT):
        return []
    return index.stored.find([mention.text], tables, groups, place_spellings=place_spellings)


def _advertisers_for_mention(
    mention: NameMention,
    index: GroundingIndex,
    place: PlaceMatch | None,
    stored: list[StoredValue],
) -> tuple[list[Advertiser], list[Advertiser]]:
    """Agency and agent hits. A resolved place or developer keeps the name from also becoming one."""
    if mention.kind not in _ENTITY_KINDS:
        return [], []
    if place is not None or _has_listing_developer(stored):
        return [], []
    agencies = index.advertisers.find_agencies(mention.text) if mention.kind is not MentionKind.AGENT else []
    if agencies and mention.kind is not MentionKind.AGENT:
        return agencies, []
    agents = index.advertisers.find_agents(mention.text) if mention.kind is not MentionKind.AGENCY else []
    return agencies, agents


def _same_brand(typed: str, stored_value: str) -> bool:
    typed_stem = brand_stem(typed) or normalize_name(typed)
    stored_stem = brand_stem(stored_value) or normalize_name(stored_value)
    return bool(typed_stem) and typed_stem == stored_stem


def _has_listing_developer(stored: list[StoredValue]) -> bool:
    return any(value.table == LISTINGS_TABLE and value.kind == "developer" for value in stored)


def _titles(agencies: list[Advertiser], agents: list[Advertiser]) -> list[str]:
    titles = [advertiser.title for advertiser in [*agencies, *agents] if advertiser.title]
    return list(dict.fromkeys(titles))


def _merge_stored(primary: list[StoredValue], extra: list[StoredValue]) -> list[StoredValue]:
    seen = {(value.table, value.column, value.value) for value in primary}
    merged = list(primary)
    for value in extra:
        key = (value.table, value.column, value.value)
        if key not in seen:
            seen.add(key)
            merged.append(value)
    return merged


def _grounded_place(match: PlaceMatch) -> GroundedPlace:
    place = match.place
    return GroundedPlace(
        title=place.title,
        breadth=place.breadth,
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
