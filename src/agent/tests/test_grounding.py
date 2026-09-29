"""Name grounding: places across both location trees, and stored spellings per column."""

from __future__ import annotations

import time

import pytest

from agent.enums.grounding import Breadth, MatchTier
from agent.enums.listing import MentionKind
from agent.grounding import GroundingIndex, ground_names
from agent.grounding.name_matching import NameMatcher, is_typo_of, name_variants
from agent.grounding.places import build_place_directory
from agent.grounding.stored_values import StoredValueIndex, learn_same_place
from agent.schemas.grounding_index import (
    ListingCountsByPlaceLink,
    LocationNode,
    NamedColumn,
    StoredValue,
)
from agent.schemas.listing import NameMention

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
    links = ListingCountsByPlaceLink(by_address_part={"dubai marina": 9, "downtown dubai": 75, "downtown jebel ali": 3})
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
    # The official area comes first: it covers every project registered under the place.
    assert [(value.column, value.value) for value in found] == [
        ("area_name_en", "Marsa Dubai"),
        ("master_project_en", "Dubai Marina"),
    ]
    assert found[0].same_place_as == "master_project_en = 'Dubai Marina'"


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
    assert grounding.unresolved_names() == []


def test_an_unknown_name_is_reported_not_dropped():
    index = GroundingIndex(places=_directory(), stored=_stored_index(), loaded_at=time.monotonic())
    grounding = ground_names([NameMention(text="Atlantis Zzyzx")], index, [DLD_SALES])
    assert grounding.unresolved_names() == ["Atlantis Zzyzx"]
    assert grounding.for_sql_prompt() == [{"name": "Atlantis Zzyzx", "unresolved": True}]


def test_a_turn_before_the_first_load_waits_for_the_index():
    import threading

    from agent.grounding.index import GroundingCache

    release = threading.Event()
    loaded = GroundingIndex(places=_directory(), stored=_stored_index(), loaded_at=time.monotonic())

    def slow_loader():
        release.wait(5)
        return loaded

    cache = GroundingCache(slow_loader, max_age_seconds=3600)
    cache.load_in_background()
    threading.Timer(0.05, release.set).start()
    assert cache.wait_for_first_load(5) is loaded


def test_a_failed_first_load_does_not_hold_later_turns():
    from agent.grounding.index import GroundingCache

    def failing_loader():
        raise RuntimeError("warehouse down")

    cache = GroundingCache(failing_loader, max_age_seconds=3600)
    cache.load_now()
    started = time.monotonic()
    assert cache.wait_for_first_load(5) is None
    assert time.monotonic() - started < 1


def test_a_legacy_node_at_the_same_spot_as_a_v2_node_joins_the_v2_place_it_sits_in():
    v2 = [
        _v2(2, None, "Dubai", Breadth.REGION),
        _v2(40, 2, "Downtown Dubai", Breadth.AREA, 25.194, 55.274),
        _v2(41, 40, "Burj Khalifa", Breadth.BUILDING, 25.1971, 55.2745),
    ]
    legacy = [
        _v2(12057, None, "Burj Khalifa", Breadth.AREA, 25.1972, 55.2744),
        _v2(12058, 12057, "Blvd Heights", Breadth.PROJECT, 25.199, 55.270),
        # Same name, far away: a different place, never linked.
        _v2(99000, None, "Burj Khalifa", Breadth.BUILDING, 24.40, 54.50),
    ]
    downtown = build_place_directory(v2, legacy, ListingCountsByPlaceLink(), region="Dubai").find("downtown").place
    assert {12057, 12058} <= downtown.legacy_ids
    assert 99000 not in downtown.legacy_ids


def test_a_legacy_node_inside_a_drawn_outline_belongs_to_that_area():
    v2 = [_v2(2, None, "Dubai", Breadth.REGION), _v2(30, 2, "Dubai Hills Estate", Breadth.AREA, 25.11, 55.26)]
    legacy = [_v2(1102, None, "DUBAI HILLS - EMERALD HILLS", Breadth.AREA, 25.1298, 55.2702)]
    directory = build_place_directory(v2, legacy, ListingCountsByPlaceLink(), region="Dubai", inside_outline={30: [1102]})
    assert 1102 in directory.find("Dubai Hills Estate").place.legacy_ids
    assert 1102 not in build_place_directory(v2, legacy, ListingCountsByPlaceLink(), region="Dubai").find(
        "Dubai Hills Estate"
    ).place.legacy_ids


def test_an_outline_does_not_claim_a_legacy_area_that_v2_places_elsewhere():
    v2 = [
        _v2(2, None, "Dubai", Breadth.REGION),
        _v2(10, 2, "Dubai Marina", Breadth.AREA, 25.083, 55.144),
        _v2(70, 2, "Dubai Harbour", Breadth.AREA, 25.095, 55.140),
    ]
    legacy = [
        _v2(311546, None, "Dubai Harbour", Breadth.AREA, 25.086, 55.143),
        _v2(309575, 311546, "SUNRISE BAY", Breadth.PROJECT, 25.096, 55.139),
        _v2(12034, None, "Palm Jumeirah", Breadth.AREA, 25.11, 55.13),
        # Filed under Palm Jumeirah; its point wrongly lands inside the Dubai Marina outline.
        _v2(276307, 12034, "ALFATTAN HOTEL & RESIDENSE", Breadth.PROJECT, 25.08, 55.14),
    ]
    directory = build_place_directory(
        v2, legacy, ListingCountsByPlaceLink(), region="Dubai", inside_outline={10: [311546, 276307]}
    )
    assert not {311546, 309575, 276307} & directory.find("Dubai Marina").place.legacy_ids
    assert {311546, 309575} <= directory.find("Dubai Harbour").place.legacy_ids


def test_a_company_name_matches_every_stored_name_that_contains_it():
    table = "public.properties"
    index = StoredValueIndex(
        [
            StoredValue(table, "developer", "Emaar", "developer", 82),
            StoredValue(table, "developer", "Emaar Properties (P.J.S.C)", "developer", 44),
            StoredValue(table, "developer", "Damac", "developer", 11),
        ],
        {},
    )
    found = index.find(["Emaar"], [table], {"developer"})
    assert [value.value for value in found] == ["Emaar", "Emaar Properties (P.J.S.C)"]


def test_a_place_name_keeps_the_exact_match_over_names_containing_it():
    table = "chatbot_ai.real_estate_transactions"
    index = StoredValueIndex(
        [
            StoredValue(table, "master_project_en", "Dubai Marina", "master_project", 97_000),
            StoredValue(table, "master_project_en", "Dubai Marina Mall", "master_project", 50),
        ],
        {},
    )
    assert [value.value for value in index.find(["Dubai Marina"], [table], {"place"})] == ["Dubai Marina"]


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("palm jumearih", "Palm Jumeirah"),
        ("bussiness bay", "Business Bay"),
        ("Ellignton Beach House", "Ellington Beach House"),
        ("Six Sense Residence", "Six Senses Residences"),
        ("Dammac Lagoon", "DAMAC Lagoons"),
        ("AI Fahidi", "Al Fahidi"),
    ],
)
def test_a_typo_keeps_every_word_and_misspells_a_few_letters(typed, stored):
    assert is_typo_of(typed, stored)


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("Jumeirah First", "Jumeirah"),
        ("business bay metro station", "Business Bay"),
        ("Pathfinder Property Development", "ACES PROPERTY DEVELOPMENT L.L.C"),
        ("DAWN Developers", "Iman Developers"),
        ("JVR", "JVC"),
    ],
)
def test_a_dropped_or_different_word_is_another_name_not_a_typo(typed, stored):
    assert not is_typo_of(typed, stored)


def test_a_misspelt_area_beats_a_tower_whose_name_spells_it_the_same_way():
    v2 = [
        _v2(2, None, "Dubai", Breadth.REGION),
        _v2(70, 2, "Palm Jumeirah", Breadth.AREA, 25.11, 55.13),
        _v2(71, 70, "MURABA RESIDENCES PALM JUMERIAH", Breadth.BUILDING, 25.12, 55.12),
    ]
    directory = build_place_directory(v2, [], ListingCountsByPlaceLink(), region="Dubai")
    match = directory.find("palm jumeriah")
    assert match.place.title == "Palm Jumeirah"
    assert match.is_approximate


def test_a_company_name_sharing_only_generic_words_is_not_matched():
    table = "public.properties"
    index = StoredValueIndex(
        [
            StoredValue(table, "developer", "ACES PROPERTY DEVELOPMENT L.L.C", "developer", 3),
            StoredValue(table, "developer", "Iman Developers", "developer", 5),
        ],
        {},
    )
    assert index.find(["pathfinder property development"], [table], {"developer"}) == []
    assert index.find(["DAWN Developers"], [table], {"developer"}) == []


def test_the_matched_place_spelling_counts_only_where_a_table_spells_it_exactly():
    index = StoredValueIndex(
        [
            StoredValue(DLD_SALES, "area_name_en", "Jumeirah First", "area", 900),
            StoredValue(DLD_SALES, "master_project_en", "Jumeirah Village Circle", "master_project", 5_000),
            StoredValue(DLD_SALES, "master_project_en", "Jumeirah Park", "master_project", 800),
        ],
        {},
    )
    found = index.find(["Jumeirah First"], [DLD_SALES], {"place"}, place_spellings=["jumeirah"])
    assert [value.value for value in found] == ["Jumeirah First"]


def test_a_station_named_after_a_place_is_read_as_that_place():
    match = _directory().find("Downtown Dubai metro station")
    assert match.place.title == "Downtown Dubai"
    assert match.is_approximate
    assert _directory().find("Mashreq metro station") is None
