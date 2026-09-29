"""Listing requirements: matched to stored amenities and views, filtered on, or reported as not checked."""

from __future__ import annotations

import time

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.enums.grounding import FeatureKind
from agent.enums.listing import ListingPurpose
from agent.enums.routing import Intent, Route, TurnKind
from agent.graph.workflow import build_chat_graph
from agent.grounding import GroundingIndex, ground_features
from agent.grounding.features import Feature, build_feature_vocabulary
from agent.grounding.places import build_place_directory
from agent.grounding.stored_values import StoredValueIndex
from agent.schemas.grounding import GroundedFeature
from agent.schemas.grounding_index import ListingCountsByPlaceLink
from agent.schemas.listing import ListingFilters
from agent.schemas.listing_search import ListingSearch
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlDraft, SqlPage
from agent.sql.listing_search import build_listing_query, search_listings
from agent.sql.lookup import _stated_listing_filters
from catalog import load_feature_aliases

AMENITIES = [
    (1, "Shared Gym"),
    (2, "Private Gym"),
    (3, "Shared Pool"),
    (4, "Private Pool"),
    (5, "Maids Room"),
    (6, "Nearby Shopping Malls"),
    (7, "Nearby Schools"),
    (8, "Central Heating"),
    (9, "Elevator"),
    (10, "Flooring"),
    (11, "Children’s Play Area"),
]
VIEWS = [(101, "Burj Khalifa View"), (102, "City Skyline View"), (103, "Ocean View"), (104, "School View"), (105, "Pool View")]

VOCABULARY = build_feature_vocabulary(
    [Feature(FeatureKind.AMENITY, key, title) for key, title in AMENITIES]
    + [Feature(FeatureKind.VIEW, key, title) for key, title in VIEWS],
    load_feature_aliases(),
)


def _titles(phrase: str) -> set[str]:
    return {feature.title for feature in VOCABULARY.match(phrase)}


@pytest.mark.parametrize(
    ("phrase", "titles"),
    [
        ("gym", {"Shared Gym", "Private Gym"}),
        ("private gym", {"Private Gym"}),
        ("maid's room", {"Maids Room"}),
        ("near a mall", {"Nearby Shopping Malls"}),
        ("near schools", {"Nearby Schools"}),
        ("elevator access", {"Elevator"}),
        ("centeral heating", {"Central Heating"}),
        ("Burj Khalifa view", {"Burj Khalifa View"}),
        ("city view", {"City Skyline View"}),
        ("sea view", {"Ocean View"}),
        ("swimming pool", {"Shared Pool", "Private Pool"}),
        ("pool", {"Shared Pool", "Private Pool"}),
        ("pool view", {"Pool View"}),
        ("children's play area", {"Children’s Play Area"}),
    ],
)
def test_a_requirement_matches_the_titles_that_hold_its_words(phrase, titles):
    assert _titles(phrase) == titles


@pytest.mark.parametrize("phrase", ["high ceilings", "marble flooring", "large windows", "quiet community", "Trakheesi permit"])
def test_a_requirement_no_title_names_matches_nothing(phrase):
    assert _titles(phrase) == set()


def test_grounded_requirements_keep_amenity_and_view_ids_apart():
    gym, view, ceilings = ground_features(["private gym", "Burj Khalifa view", "high ceilings"], VOCABULARY)
    assert (gym.amenity_ids, gym.view_ids) == ([2], [])
    assert (view.amenity_ids, view.view_ids) == ([], [101])
    assert not ceilings.is_resolved and ceilings.text == "high ceilings"


GYM = GroundedFeature(text="gym", amenity_ids=[1, 2], titles=["Private Gym", "Shared Gym"])
POOL_OR_VIEW = GroundedFeature(text="pool", amenity_ids=[3], view_ids=[103], titles=["Ocean View", "Shared Pool"])


def test_every_requirement_is_required_unless_any_one_will_do():
    every = build_listing_query(ListingSearch(filters=ListingFilters(), features=[GYM, POOL_OR_VIEW]), limit=10, offset=0)
    assert "ap.amenity_id = ANY(%(feature_0_amenity_ids)s)" in every.sql
    assert "pv.view_id = ANY(%(feature_1_view_ids)s)" in every.sql
    assert ") AND (EXISTS" in every.sql
    assert every.params["feature_0_amenity_ids"] == [1, 2]
    assert every.params["feature_1_view_ids"] == [103]

    either = build_listing_query(
        ListingSearch(filters=ListingFilters(), features=[GYM, POOL_OR_VIEW], any_feature=True), limit=10, offset=0
    )
    assert ") OR (EXISTS" in either.sql


class _CountingRunner:
    def __init__(self, totals: list[int]) -> None:
        self.totals = list(totals)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, sql: str, params: dict | None = None) -> SqlPage:
        self.calls.append((sql, dict(params or {})))
        if sql.startswith("SELECT count(*)"):
            total = self.totals.pop(0) if len(self.totals) > 1 else self.totals[0]
            return SqlPage(columns=["total"], rows=[{"total": total}], truncated=False, duration_ms=1)
        return SqlPage(columns=["property_id"], rows=[{"property_id": 7}], truncated=False, duration_ms=1)


def test_an_unchecked_requirement_is_reported_and_not_filtered_on():
    runner = _CountingRunner([4])
    search = ListingSearch(filters=ListingFilters(), unchecked_requirements=["high ceilings"])
    result = search_listings(search, runner, limit=10, offset=0)
    assert result.total == 4
    assert result.notes == ["The search could not check high ceilings, so these results may not have it."]
    assert "amenity_property" not in runner.calls[0][0]


def test_features_are_the_last_thing_loosened():
    runner = _CountingRunner([0, 0, 5])
    search = ListingSearch(filters=ListingFilters(price_max=100), features=[GYM])
    result = search_listings(search, runner, limit=10, offset=0)
    assert result.total == 5
    assert "price" in result.notes[0]
    assert "gym" in result.notes[1]
    assert "feature_0_amenity_ids" in runner.calls[1][1]
    assert "feature_0_amenity_ids" not in runner.calls[2][1]


def test_the_reply_is_told_which_features_the_search_required():
    search = ListingSearch(filters=ListingFilters(requirements=["gym", "pool"]), features=[GYM, POOL_OR_VIEW])
    assert _stated_listing_filters(search) == ["has: Private Gym or Shared Gym; Ocean View or Shared Pool"]
    either = ListingSearch(filters=ListingFilters(), features=[GYM, POOL_OR_VIEW], any_feature=True)
    assert _stated_listing_filters(either)[0].startswith("has any of: ")


class _FeatureModels:
    def __init__(self) -> None:
        self.answers: list[dict] = []

    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            intent=Intent.LIST,
            purpose="sale",
            names=[],
            listing_filters=ListingFilters(
                purpose=ListingPurpose.SALE, requirements=["private gym", "Burj Khalifa view", "high ceilings"]
            ),
            confidence=0.9,
            rationale="Show listings.",
        )

    def route_domain(self, **kwargs) -> DomainRoute:
        return DomainRoute(domain_ids=["listings"], join_ids=[], confidence=0.9, rationale="Listings.")

    def draft_sql(self, **kwargs) -> SqlDraft:
        raise AssertionError("a property search never drafts SQL")

    def answer_from_sql(self, **kwargs) -> str:
        self.answers.append(kwargs)
        return "Here are the listings."


def test_a_turn_filters_on_matched_requirements_and_tells_the_reply_about_the_rest():
    index = GroundingIndex(
        places=build_place_directory([], [], ListingCountsByPlaceLink(), region="Dubai"),
        stored=StoredValueIndex([], {}, {}),
        loaded_at=time.monotonic(),
        features=VOCABULARY,
    )
    models = _FeatureModels()
    runner = _CountingRunner([2])
    build_chat_graph(InMemorySaver()).invoke(
        {"messages": [HumanMessage(content="apartments with a private gym, Burj Khalifa view and high ceilings")]},
        config={"configurable": {"thread_id": "features", "user_id": "user-1"}},
        context=AgentContext(
            user_id="user-1", models=models, sql_runner=runner, listing_loader=lambda ids: [], grounding=index
        ),
    )
    _, params = runner.calls[0]
    assert params["feature_0_amenity_ids"] == [2]
    assert params["feature_1_view_ids"] == [101]
    answer = models.answers[0]
    assert "has: Private Gym; Burj Khalifa View" in answer["filters"]
    assert any("high ceilings" in note for note in answer["search_notes"])
