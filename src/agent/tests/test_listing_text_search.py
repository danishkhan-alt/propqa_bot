"""Description phrases match listing text, and that match is never dropped for a type-wide search."""

from __future__ import annotations

from agent.enums.listing import ListingPurpose, ListingSort
from agent.enums.routing import Intent, Route, TurnKind
from agent.schemas.grounding import GroundedFeature, Grounding
from agent.schemas.listing import ListingFilters
from agent.schemas.listing_search import ListingSearch
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlPage
from agent.sql.execute import SqlFailed
from agent.sql.listing_search import build_listing_query, resolve_category_ids, search_listings
from agent.sql.listing_text_search import broaden_with_synonyms, build_text_query
from agent.sql.lookup import run_listing_lookup
from agent.tests.test_listing_features import GYM

_SYNONYMS = '"double height" OR "double volume" OR "high ceiling" OR "high ceilings"'


def test_a_description_phrase_is_quoted_and_generic_tails_are_trimmed():
    assert build_text_query(["high ceilings"]) == '"high ceilings"'
    assert build_text_query(["double height living room"]) == '"double height"'
    assert build_text_query(["large windows", "natural light"]) == '"large windows" "natural light"'
    assert build_text_query(["with a high ceilings"]) == '"high ceilings"'
    assert build_text_query(["or"]) is None


def test_similar_wording_is_an_or_and_unknown_wording_is_not():
    assert broaden_with_synonyms(["double height living room"]) == _SYNONYMS
    assert broaden_with_synonyms(["marble floors"]) is None


def test_the_query_stays_within_the_character_cap(monkeypatch):
    monkeypatch.setattr("agent.sql.listing_text_search.ActiveConfig.LISTING_TEXT_QUERY_MAX_CHARS", 20)
    query = build_text_query(["high ceilings", "natural light"])
    assert query == '"high ceilings"'
    assert len(query) <= 20


def test_the_text_match_is_bound_and_ranks_only_the_default_sort():
    search = ListingSearch(
        filters=ListingFilters(),
        text_requirements=["high ceilings"],
        text_query='"high ceilings"',
    )
    query = build_listing_query(search, limit=10, offset=0)
    assert query.params["text_query"] == '"high ceilings"'
    assert "high ceilings" not in query.sql
    assert "p.search_vector @@ websearch_to_tsquery('english', %(text_query)s)" in query.sql
    assert query.sql.index("ORDER BY ts_rank") < query.sql.index("p.created_at")

    priced = build_listing_query(
        ListingSearch(filters=ListingFilters(sort=ListingSort.PRICE_LOW), text_query='"high ceilings"'),
        limit=10,
        offset=0,
    )
    assert "ts_rank" not in priced.sql
    assert "COALESCE(p.price_max, p.price_min) ASC" in priced.sql


def test_a_catalog_feature_matches_its_tag_or_the_listing_text():
    query = build_listing_query(
        ListingSearch(filters=ListingFilters(), features=[GYM], match_features_in_text=True),
        limit=10,
        offset=0,
    )
    assert "amenity_property" in query.sql
    assert (
        "ap.amenity_id = ANY(%(feature_0_amenity_ids)s)) "
        "OR p.search_vector @@ websearch_to_tsquery('english', %(feature_0_text)s)"
    ) in query.sql
    assert query.params["feature_0_text"] == '"gym"'
    assert "gym" not in query.sql


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


def _text_search(property_types: list[str], phrase: str, **filter_values) -> ListingSearch:
    return ListingSearch(
        filters=ListingFilters(property_types=property_types, **filter_values),
        text_requirements=[phrase],
        text_query=build_text_query([phrase]),
    )


def test_a_miss_tries_similar_wording_then_the_villa_family_and_keeps_the_text_match():
    runner = _CountingRunner([0, 0, 1])
    result = search_listings(_text_search(["villa"], "double height living room"), runner, limit=10, offset=0)
    assert result.total == 1
    assert [params["text_query"] for sql, params in runner.calls if sql.startswith("SELECT count(*)")] == [
        '"double height"',
        _SYNONYMS,
        _SYNONYMS,
    ]
    family_ids, unknown = resolve_category_ids(["villa", "villa compound"])
    assert not unknown
    assert set(runner.calls[2][1]["category_ids"]) == set(family_ids)
    assert "similar wording" in result.notes[0]
    assert result.notes[1] == "No villas mention double height living room, so villa compounds are included."
    assert all("search_vector" in sql and "text_query" in params for sql, params in runner.calls)


def test_other_types_are_disclosed_when_the_villa_family_also_misses():
    runner = _CountingRunner([0, 0, 0, 5])
    result = search_listings(_text_search(["villa"], "double height living room"), runner, limit=10, offset=0)
    assert result.total == 5
    assert "category_ids" not in runner.calls[3][1]
    assert runner.calls[3][1]["text_query"] == _SYNONYMS
    assert "similar wording" in result.notes[0]
    assert "villa compounds are included" in result.notes[1]
    assert result.notes[2] == (
        "No villas or villa compounds mention double height living room; these 5 other listings do."
    )


def test_other_property_types_are_shown_with_a_count_when_the_asked_type_has_none():
    runner = _CountingRunner([0, 4])
    result = search_listings(_text_search(["apartment"], "marble floors"), runner, limit=10, offset=0)
    assert result.total == 4
    assert "category_ids" not in runner.calls[1][1]
    assert runner.calls[1][1]["text_query"] == '"marble floors"'
    assert result.notes == ["No apartments mention marble floors; these 4 other listings do."]


def test_a_text_match_is_never_dropped_when_nothing_else_matches():
    runner = _CountingRunner([0, 0])
    result = search_listings(_text_search(["apartment"], "marble floors"), runner, limit=10, offset=0)
    assert result.total == 0
    assert result.ids == []
    assert all(params.get("text_query") == '"marble floors"' for _, params in runner.calls)
    assert len(runner.calls) == 2


def test_loosening_price_still_requires_the_text_match():
    runner = _CountingRunner([0, 0, 2])
    result = search_listings(_text_search(["apartment"], "marble floors", price_max=100), runner, limit=10, offset=0)
    assert result.total == 2
    assert all(params.get("text_query") == '"marble floors"' for _, params in runner.calls)
    assert "price_max" not in runner.calls[-1][1]


def _lookup_state(filters: ListingFilters) -> dict:
    return {
        "query_route": QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            intent=Intent.LIST,
            listing_filters=filters,
            confidence=0.9,
            rationale="Show listings.",
        ),
        "domain_route": DomainRoute(domain_ids=["listings"], join_ids=[], confidence=0.9, rationale="Listings."),
        "grounding": Grounding(features=[GroundedFeature(text="high ceilings")]),
    }


class _TextSearchFails:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, sql: str, params: dict | None = None) -> SqlPage:
        self.calls.append((sql, dict(params or {})))
        if "search_vector" in sql:
            raise SqlFailed("search_vector is missing")
        if sql.startswith("SELECT count(*)"):
            return SqlPage(columns=["total"], rows=[{"total": 3}], truncated=False, duration_ms=1)
        return SqlPage(columns=["property_id"], rows=[{"property_id": 9}], truncated=False, duration_ms=1)


def test_a_text_search_failure_retries_only_when_another_filter_remains():
    bounded = _TextSearchFails()
    found = run_listing_lookup(_lookup_state(ListingFilters(bedrooms_min=2)), bounded)
    assert found["sql_result"]["status"] == "rows"
    assert found["listing_ids"] == ["9"]
    assert "search_vector" in bounded.calls[0][0]
    assert all("search_vector" not in sql for sql, _ in bounded.calls[1:])
    assert any("could not check high ceilings" in note for note in found["sql_result"]["notes"])

    open_search = _TextSearchFails()
    failed = run_listing_lookup(_lookup_state(ListingFilters(purpose=ListingPurpose.SALE)), open_search)
    assert failed["sql_result"]["status"] == "failed"
    assert len(open_search.calls) == 1

