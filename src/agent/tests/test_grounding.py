"""Name grounding: places across both location trees, and stored spellings per column."""

from __future__ import annotations

import time

from agent.grounding import GroundingIndex, ground_names
from agent.grounding.names import MatchTier, NameMatcher, name_variants
from agent.grounding.places import Breadth, ListingLinks, LocationNode, build_place_directory
from agent.grounding.stored_values import NamedColumn, StoredValue, StoredValueIndex, learn_same_place
from agent.schemas.listing import MentionKind, NameMention

DLD_SALES = "chatbot_ai.real_estate_transactions"
OFFPLAN = "public.offplan_projects_new"


def _v2(node_id, parent_id, title, breadth, lat=None, lng=None, aliases=()):
    return LocationNode(node_id, parent_id, title, breadth, tuple(aliases), lat, lng)


def _directory(aliases=None):
    v2 = [
        _v2(1, None, "UAE", Breadth.REGION),
        _v2(2, 1, "Dubai", Breadth.REGION),
        _v2(3, 1, "Ajman", Breadth.REGION),
        _v2(10, 2, "Dubai Marina", Breadth.AREA, 25.083, 55.144),
        _v2(11, 10, "Marina Gate", Breadth.BUILDING, 25.086, 55.146),
        _v2(12, 10, "Rove Dubai Marina", Breadth.BUILDING, 25.080, 55.140),
        _v2(20, 2, "Jumeirah Village Circle (JVC)", Breadth.AREA, 25.059, 55.208),
        _v2(21, 20, "Binghatti Lavender", Breadth.BUILDING, 25.060, 55.210),
        _v2(30, 2, "Dubai Hills Estate", Breadth.AREA, 25.1145, 55.2589),
        _v2(31, 30, "Sidra", Breadth.PROJECT, 25.100, 55.250),
        _v2(32, 2, "Dubai Hills View", Breadth.AREA, 25.1165, 55.2678),
        _v2(40, 2, "Downtown Dubai", Breadth.AREA, 25.194, 55.274),
        _v2(41, 2, "Downtown Jebel Ali", Breadth.AREA, 24.99, 55.10),
        _v2(50, 3, "Ajman Downtown", Breadth.AREA, 25.40, 55.45),
        _v2(60, 2, "Jumeirah Lake Towers (JLT)", Breadth.AREA, 25.07, 55.14),
    ]
    legacy = [
        _v2(1001, None, "Dubai Marina", Breadth.AREA, 25.0807, 55.1398),
        _v2(1002, 1001, "Marina Place 1", Breadth.PROJECT, 25.3, 55.3),
        _v2(1100, None, "DUBAI HILLS", Breadth.AREA, 25.1156, 55.2682),
        _v2(1101, None, "DUBAI HILLS - SIDRA 1", Breadth.AREA, 25.0933, 55.2504),
        _v2(1200, None, "Jumeirah Village Circle", Breadth.AREA, 25.061, 55.209),
        _v2(1300, None, "DownTown Dubai", Breadth.AREA, 25.195, 55.275),
    ]
    links = ListingLinks(by_address_part={"dubai marina": 9, "downtown dubai": 75, "downtown jebel ali": 3})
    return build_place_directory(v2, legacy, links, region="Dubai", aliases=aliases)


def test_a_stored_name_answers_to_its_bracket_and_short_form():
    assert name_variants("Jumeirah Village Circle (JVC)") == {
        "jumeirah village circle jvc",
        "jumeirah village circle",
        "jvc",
    }


def test_an_exact_name_beats_a_containing_one_and_a_typo_is_still_found():
    matcher: NameMatcher[str] = NameMatcher()
    matcher.add("marina", ["Dubai Marina"])
    matcher.add("mall", ["Dubai Marina Mall"])

    exact = matcher.find("dubai marina")
    assert [(hit.key, hit.tier) for hit in exact] == [("marina", MatchTier.EXACT)]

    words = {hit.key: hit.tier for hit in matcher.find("marina")}
    assert words == {"marina": MatchTier.WORDS, "mall": MatchTier.WORDS}

    typo = matcher.find("dubia marina")
    assert typo and typo[0].tier is MatchTier.FUZZY
    assert max(typo, key=lambda hit: hit.coverage).key == "marina"


def test_a_short_name_means_the_area_not_a_tower_in_it():
    match = _directory().find("marina")
    assert match is not None
    assert match.place.title == "Dubai Marina"
    assert match.place.breadth is Breadth.AREA
    assert "Marina Gate" in match.alternatives


def test_one_place_carries_both_trees_and_every_address_spelling():
    place = _directory().find("JVC").place
    assert place.title == "Jumeirah Village Circle (JVC)"
    assert {20, 21} <= place.v2_ids
    assert 1200 in place.legacy_ids
    assert {"jumeirah village circle (jvc)", "jumeirah village circle"} <= place.address_names


def test_a_legacy_subtree_is_part_of_the_place():
    place = _directory().find("dubai marina").place
    assert {10, 11, 12} <= place.v2_ids
    assert {1001, 1002} <= place.legacy_ids


def test_a_place_covers_nearby_places_whose_names_extend_it_but_not_the_reverse():
    directory = _directory()
    hills = directory.find("Dubai Hills").place
    assert hills.title == "DUBAI HILLS"
    # Dubai Hills Estate (v2) and Dubai Hills View are within the radius; SIDRA 1 is too far.
    assert {30, 31, 32} <= hills.v2_ids
    assert "dubai hills estate" in hills.address_names
    assert 1101 not in hills.legacy_ids

    view = directory.find("Dubai Hills View").place
    assert view.v2_ids == {32}


def test_the_region_itself_is_no_filter_and_other_regions_are_left_out():
    directory = _directory()
    assert directory.find("Dubai") is None
    downtown = directory.find("downtown").place
    assert downtown.title == "Downtown Dubai"
    assert directory.find("Ajman Downtown") is None


def test_a_typo_is_matched_and_marked_approximate():
    match = _directory().find("dubia marina")
    assert match is not None
    assert match.place.title == "Dubai Marina"
    assert match.is_approximate


def test_same_place_is_learned_only_when_the_rows_agree():
    column = NamedColumn(DLD_SALES, "master_project_en", "master_project", same_place_as="area_name_en")
    learned = learn_same_place(
        column,
        "area",
        [
            ("Dubai Marina", "Marsa Dubai", 97_000),
            ("Dubai Marina", "Al Sufouh", 100),
            ("Mixed Project", "Area One", 50),
            ("Mixed Project", "Area Two", 50),
            ("Palm Jumeirah", "Palm Jumeirah", 40_000),
        ],
    )
    assert set(learned) == {(DLD_SALES, "master_project_en", "Dubai Marina")}
    official = learned[(DLD_SALES, "master_project_en", "Dubai Marina")]
    assert (official.column, official.value) == ("area_name_en", "Marsa Dubai")


def _stored_index(aliases=None) -> StoredValueIndex:
    values = [
        StoredValue(DLD_SALES, "area_name_en", "Marsa Dubai", "area", 137_000),
        StoredValue(DLD_SALES, "area_name_en", "Burj Khalifa", "area", 73_000),
        StoredValue(DLD_SALES, "area_name_en", "Al Thanyah Fifth", "area", 98_000),
        StoredValue(DLD_SALES, "master_project_en", "Dubai Marina", "master_project", 97_000),
        StoredValue(DLD_SALES, "master_project_en", "DownTown Dubai", "master_project", 72_000),
        StoredValue(DLD_SALES, "project_name_en", "Marina Gate", "project", 900),
        StoredValue(DLD_SALES, "project_name_en", "SEVEN CITY JLT", "project", 3_580),
        StoredValue(OFFPLAN, "developer_name_en", "Emaar Properties", "developer", 120),
        StoredValue(OFFPLAN, "project_name_en", "Emaar Beachfront", "project", 40),
    ]
    column = NamedColumn(DLD_SALES, "master_project_en", "master_project", same_place_as="area_name_en")
    same_place = learn_same_place(
        column,
        "area",
        [("Dubai Marina", "Marsa Dubai", 97_000), ("DownTown Dubai", "Burj Khalifa", 72_000)],
    )
    return StoredValueIndex(values, same_place, aliases)


def test_the_broadest_stored_name_wins_and_brings_its_official_area():
    found = _stored_index().find(["marina"], [DLD_SALES], {"place"})
    assert [(value.column, value.value) for value in found] == [
        ("master_project_en", "Dubai Marina"),
        ("area_name_en", "Marsa Dubai"),
    ]
    assert found[1].same_place_as == "master_project_en = 'Dubai Marina'"


def test_a_developer_name_never_matches_a_project_named_after_it():
    index = _stored_index()
    developers = index.find(["Emaar"], [OFFPLAN], {"developer"})
    assert [value.value for value in developers] == ["Emaar Properties"]
    assert index.find(["Emaar"], [DLD_SALES], {"developer"}) == []


def test_curated_wording_reaches_the_stored_name_and_outranks_a_partial_match():
    index = _stored_index(aliases={"jumeirah lake towers": ["Al Thanyah Fifth"]})
    found = index.find(["Jumeirah Lake Towers (JLT)", "jumeirah lake towers", "jlt"], [DLD_SALES], {"place"})
    assert [value.value for value in found] == ["Al Thanyah Fifth"]


def test_grounding_uses_the_place_spelling_to_find_other_sources():
    index = GroundingIndex(places=_directory(), stored=_stored_index(), loaded_at=time.monotonic())
    grounding = ground_names(
        [NameMention(text="downtown"), NameMention(text="Emaar", kind=MentionKind.DEVELOPER)],
        index,
        [DLD_SALES, OFFPLAN],
    )
    downtown, emaar = grounding.names
    assert downtown.place.title == "Downtown Dubai"
    assert {(match.column, match.value) for match in downtown.stored} == {
        ("master_project_en", "DownTown Dubai"),
        ("area_name_en", "Burj Khalifa"),
    }
    assert emaar.place is None
    assert [match.value for match in emaar.stored] == ["Emaar Properties"]
    assert grounding.unresolved() == []


def test_an_unknown_name_is_reported_not_dropped():
    index = GroundingIndex(places=_directory(), stored=_stored_index(), loaded_at=time.monotonic())
    grounding = ground_names([NameMention(text="Atlantis Zzyzx")], index, [DLD_SALES])
    assert grounding.unresolved() == ["Atlantis Zzyzx"]
    assert grounding.for_sql_prompt() == [{"name": "Atlantis Zzyzx", "unresolved": True}]
    assert "searched as text" in grounding.notes()[0]
