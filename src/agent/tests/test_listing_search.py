"""Property search written in code, and the model-drafted path's use of grounded names."""

from __future__ import annotations

import time

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.enums.routing import Intent, Route, TurnKind
from agent.graphs.chat import build_chat_graph
from agent.grounding import GroundingIndex
from agent.grounding.places import Breadth, ListingLinks, LocationNode, build_place_directory
from agent.grounding.stored_values import StoredValue, StoredValueIndex
from agent.schemas.grounding import GroundedName, GroundedPlace, Grounding
from agent.schemas.listing import ListingFilters, ListingSort, MentionKind, NameMention
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlDraft
from agent.sql.execute import SqlPage
from agent.sql.listing_search import (
    ListingSearch,
    build_listing_query,
    category_ids,
    listing_purpose,
    search_listings,
)
from agent.sql.lookup import ONLY_ZERO_VALUES, run_sql_lookup

MARINA = GroundedPlace(
    title="Dubai Marina",
    v2_ids=[10, 11],
    legacy_ids=[1001],
    address_names=["dubai marina"],
)


class _CountingRunner:
    """Answers count statements from `totals`, in order, and page statements with ids."""

    def __init__(self, totals: list[int], ids: list[int] | None = None) -> None:
        self.totals = list(totals)
        self.ids = ids or []
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, sql: str, params: dict | None = None) -> SqlPage:
        self.calls.append((sql, dict(params or {})))
        if sql.startswith("SELECT count(*)"):
            total = self.totals.pop(0) if len(self.totals) > 1 else self.totals[0]
            return SqlPage(columns=["total"], rows=[{"total": total}], truncated=False, duration_ms=1)
        rows = [{"property_id": listing_id} for listing_id in self.ids]
        return SqlPage(columns=["property_id"], rows=rows, truncated=False, duration_ms=1)


def test_a_place_matches_any_way_a_listing_points_at_it():
    query = build_listing_query(
        ListingSearch(filters=ListingFilters(), purpose="for_sale", places=[MARINA]),
        limit=10,
        offset=0,
    )
    assert "p.status = 'active' AND p.deleted_at IS NULL" in query.sql
    assert "p.location_v2_id = ANY(%(place_v2_ids)s)" in query.sql
    for column in ("location_master_project_id", "location_project_id", "location_building_id"):
        assert f"p.{column} = ANY(%(place_legacy_ids)s)" in query.sql
    assert "trim(part) = ANY(%(place_address_names)s)" in query.sql
    assert query.params["place_v2_ids"] == [10, 11]
    assert query.params["place_legacy_ids"] == [1001]
    assert query.params["place_address_names"] == ["dubai marina"]
    assert query.params["purpose"] == "for_sale"


def test_filters_become_parameters_and_price_reads_the_filled_column():
    filters = ListingFilters(
        property_types=["apartments"],
        bedrooms_min=2,
        bedrooms_max=2,
        price_max=1_500_000,
        sort=ListingSort.PRICE_LOW,
    )
    query = build_listing_query(ListingSearch(filters=filters), limit=5, offset=10)
    assert "COALESCE(p.price_max, p.price_min) <= %(price_max)s" in query.sql
    assert "p.rooms >= %(bedrooms_min)s" in query.sql and "p.rooms <= %(bedrooms_max)s" in query.sql
    assert query.params["category_ids"] == [50]
    assert query.params["price_max"] == 1_500_000
    assert query.sql.index("ORDER BY COALESCE(p.price_max, p.price_min) ASC NULLS LAST")
    assert (query.params["limit"], query.params["offset"]) == (5, 10)
    assert "1500000" not in query.sql


def test_types_map_to_catalog_categories_and_unknown_types_are_reported():
    ids, unknown = category_ids(["Villas", "hotel apartment", "Penthouse", "castle"])
    assert ids == [3, 22, 33]
    assert unknown == ["castle"]


@pytest.mark.parametrize(
    ("stated", "stored"),
    [("sale", "for_sale"), ("to buy", "for_sale"), ("rent", "for_rent"), ("for_rent", "for_rent"), (None, None)],
)
def test_purpose_is_read_from_what_the_user_said(stated, stored):
    assert listing_purpose(stated) == stored


def test_an_unmatched_place_is_searched_as_address_text_not_dropped():
    query = build_listing_query(
        ListingSearch(filters=ListingFilters(), unmatched_places=["Zzyzx_50%"]),
        limit=10,
        offset=0,
    )
    assert "p.address_en ILIKE ANY(%(place_address_patterns)s)" in query.sql
    assert query.params["place_address_patterns"] == ["%Zzyzx\\_50\\%%"]


def test_nothing_matching_relaxes_price_first_and_says_so():
    runner = _CountingRunner(totals=[0, 3], ids=[7, 8, 9])
    filters = ListingFilters(price_max=100, bedrooms_min=2, bedrooms_max=2)
    result = search_listings(ListingSearch(filters=filters, places=[MARINA]), runner, limit=10, offset=0)
    assert result.ids == ["7", "8", "9"]
    assert result.total == 3
    assert len(result.notes) == 1 and "price" in result.notes[0]
    page_sql, page_params = runner.calls[-1]
    assert "price_max" not in page_params
    assert page_params["bedrooms_min"] == 2
    assert page_params["place_v2_ids"] == [10, 11]


def test_the_place_is_never_relaxed_away():
    runner = _CountingRunner(totals=[0])
    filters = ListingFilters(price_max=100, bedrooms_min=2, bedrooms_max=2)
    result = search_listings(ListingSearch(filters=filters, places=[MARINA]), runner, limit=10, offset=0)
    assert result.ids == [] and result.total == 0
    assert all("place_v2_ids" in params for _, params in runner.calls)
    assert len(result.notes) == 2


def _index() -> GroundingIndex:
    v2 = [
        LocationNode(2, None, "Dubai", Breadth.REGION),
        LocationNode(10, 2, "Dubai Marina", Breadth.AREA, lat=25.08, lng=55.14),
        LocationNode(11, 10, "Marina Gate", Breadth.BUILDING, lat=25.09, lng=55.15),
    ]
    places = build_place_directory(v2, [], ListingLinks(), region="Dubai")
    stored = StoredValueIndex(
        [StoredValue("chatbot_ai.real_estate_transactions", "area_name_en", "Marsa Dubai", "area", 10)],
        {},
        {"dubai marina": ["Marsa Dubai"]},
    )
    return GroundingIndex(places=places, stored=stored, loaded_at=time.monotonic())


class _ListingModels:
    def __init__(self) -> None:
        self.sql_drafts = 0
        self.answers: list[dict] = []

    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            intent=Intent.LIST,
            purpose="sale",
            names=[NameMention(text="marina")],
            listing_filters=ListingFilters(bedrooms_min=2, bedrooms_max=2),
            confidence=0.9,
            rationale="Show listings.",
        )

    def route_domain(self, **kwargs) -> DomainRoute:
        return DomainRoute(domain_ids=["listings"], join_ids=["locations"], confidence=0.9, rationale="Listings.")

    def answer_direct(self, **kwargs) -> str:
        return "hello"

    def answer_unavailable(self, **kwargs) -> str:
        return "unavailable"

    def draft_sql(self, **kwargs) -> SqlDraft:
        self.sql_drafts += 1
        return SqlDraft(sql="SELECT 1", purpose="should not run")

    def answer_from_sql(self, **kwargs) -> str:
        self.answers.append(kwargs)
        return "Here are the listings."


def test_a_property_search_turn_never_asks_the_model_for_sql():
    models = _ListingModels()
    runner = _CountingRunner(totals=[2], ids=[101, 102])
    graph = build_chat_graph(InMemorySaver())
    state = graph.invoke(
        {"messages": [HumanMessage(content="2 bed properties for sale in marina")]},
        config={"configurable": {"thread_id": "listing-search", "user_id": "user-1"}},
        context=AgentContext(
            user_id="user-1",
            models=models,
            sql_runner=runner,
            listing_loader=lambda ids: [],
            grounding=_index(),
        ),
    )
    assert models.sql_drafts == 0
    _, params = runner.calls[0]
    assert params["place_v2_ids"] == [10, 11]
    assert params["purpose"] == "for_sale"
    assert params["bedrooms_min"] == 2
    assert models.answers and models.answers[0]["listing_ids"] == ["101", "102"]
    assert state["grounding"] is None
    assert state["last_need_db"].result_meta["listing_filters"] == {"bedrooms_min": 2, "bedrooms_max": 2}


class _DraftRecorder:
    def __init__(self, drafts: list[str]) -> None:
        self.drafts = list(drafts)
        self.calls: list[dict] = []

    def draft_sql(self, **kwargs) -> SqlDraft:
        self.calls.append(kwargs)
        return SqlDraft(sql=self.drafts[min(len(self.calls), len(self.drafts)) - 1], purpose="count")


def _sales_state() -> dict:
    return {
        "messages": [HumanMessage(content="How many sales in downtown in 2025?")],
        "domain_route": DomainRoute(domain_ids=["transactions"], join_ids=[], confidence=1, rationale="Sales."),
        "catalog_context": "real_estate_transactions",
        "grounding": Grounding(
            names=[
                GroundedName(
                    text="downtown",
                    kind=MentionKind.PLACE,
                    stored=[
                        {
                            "table": "chatbot_ai.real_estate_transactions",
                            "column": "area_name_en",
                            "value": "Burj Khalifa",
                            "kind": "area",
                        }
                    ],
                )
            ]
        ),
    }


def test_resolved_names_reach_the_sql_model():
    models = _DraftRecorder(["SELECT count(*) AS n FROM real_estate_transactions"])
    pages = [SqlPage(columns=["n"], rows=[{"n": 4091}], truncated=False, duration_ms=1)]
    run_sql_lookup(_sales_state(), models, lambda sql: pages[0])
    resolved = models.calls[0]["resolved_names"]
    assert resolved == [
        {
            "name": "downtown",
            "stored_values": [{"column": "chatbot_ai.real_estate_transactions.area_name_en", "value": "Burj Khalifa"}],
        }
    ]


def test_an_all_zero_aggregate_is_retried_with_the_reason():
    models = _DraftRecorder(
        [
            "SELECT count(*) AS n FROM real_estate_transactions WHERE area_name_en ILIKE '%Downtown%'",
            "SELECT count(*) AS n FROM real_estate_transactions WHERE area_name_en = 'Burj Khalifa'",
        ]
    )
    pages = iter(
        [
            SqlPage(columns=["n"], rows=[{"n": 0}], truncated=False, duration_ms=1),
            SqlPage(columns=["n"], rows=[{"n": 4091}], truncated=False, duration_ms=1),
        ]
    )
    update = run_sql_lookup(_sales_state(), models, lambda sql: next(pages))
    assert len(models.calls) == 2
    assert models.calls[1]["previous_error"] == ONLY_ZERO_VALUES
    assert update["sql_rows"] == [{"n": 4091}]


def test_a_failed_retry_keeps_the_answer_it_was_retrying():
    models = _DraftRecorder(["SELECT count(*) AS n FROM real_estate_transactions", "DELETE FROM x"])
    page = SqlPage(columns=["n"], rows=[{"n": 0}], truncated=False, duration_ms=1)
    update = run_sql_lookup(_sales_state(), models, lambda sql: page)
    assert update["sql_result"]["status"] == "rows"
    assert update["sql_rows"] == [{"n": 0}]
