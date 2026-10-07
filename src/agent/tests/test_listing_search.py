"""Property search written in code, and the model-drafted path's use of grounded names."""

from __future__ import annotations

import time

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.enums.grounding import Breadth
from agent.enums.listing import ListingPurpose, ListingSort, MentionKind, NearStation
from agent.enums.routing import Intent, Route, TurnKind
from agent.graph.workflow import build_chat_graph
from agent.grounding import GroundingIndex
from agent.grounding.places import build_place_directory
from agent.grounding.stored_values import StoredValueIndex
from agent.schemas.grounding import GroundedName, GroundedPlace, Grounding
from agent.schemas.grounding_index import ListingCountsByPlaceLink, LocationNode, StoredValue
from agent.schemas.listing import GOLDEN_VISA_MIN_PRICE_AED, ListingFilters, NameMention
from agent.schemas.listing_search import ListingSearch
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlDraft, SqlPage
from agent.sql.listing_search import build_listing_query, resolve_category_ids, search_listings
from agent.sql.lookup import ALL_ZERO_ROW_RETRY_REASON, run_sql_lookup

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
        ListingSearch(filters=ListingFilters(purpose=ListingPurpose.SALE), places=[MARINA]),
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
    assert query.params["category_ids"] == [25]
    assert query.params["price_max"] == 1_500_000
    assert query.sql.index("ORDER BY COALESCE(p.price_max, p.price_min) ASC NULLS LAST")
    assert (query.params["limit"], query.params["offset"]) == (5, 10)
    assert "1500000" not in query.sql


def test_types_map_to_catalog_categories_and_unknown_types_are_reported():
    ids, unknown = resolve_category_ids(["Villas", "hotel apartment", "Penthouse", "castle"])
    assert ids == [24, 20, 22]
    assert unknown == ["castle"]


@pytest.mark.parametrize(
    ("purpose", "stored"),
    [(ListingPurpose.SALE, "for_sale"), (ListingPurpose.RENT, "for_rent"), (ListingPurpose.ANY, None)],
)
def test_purpose_maps_to_the_stored_value_and_any_adds_no_filter(purpose, stored):
    query = build_listing_query(ListingSearch(filters=ListingFilters(purpose=purpose)), limit=10, offset=0)
    assert query.params.get("purpose") == stored
    assert ("p.purpose = %(purpose)s" in query.sql) is (stored is not None)


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
    places = build_place_directory(v2, [], ListingCountsByPlaceLink(), region="Dubai")
    stored = StoredValueIndex(
        [StoredValue("public.real_estate_dld_transactions", "area_name_en", "Marsa Dubai", "area", 10)],
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
            listing_filters=ListingFilters(purpose=ListingPurpose.SALE, bedrooms_min=2, bedrooms_max=2),
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
    assert models.answers and models.answers[0]["listing_count"] == 2
    assert state["grounding"] is None
    assert state["last_need_db"].result_meta["listing_filters"] == {
        "purpose": "sale",
        "bedrooms_min": 2,
        "bedrooms_max": 2,
    }


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
        "catalog_context": "real_estate_dld_transactions",
        "grounding": Grounding(
            names=[
                GroundedName(
                    text="downtown",
                    kind=MentionKind.PLACE,
                    stored=[
                        {
                            "table": "public.real_estate_dld_transactions",
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
    models = _DraftRecorder(["SELECT count(*) AS n FROM real_estate_dld_transactions"])
    pages = [SqlPage(columns=["n"], rows=[{"n": 4091}], truncated=False, duration_ms=1)]
    run_sql_lookup(_sales_state(), models, lambda sql: pages[0])
    resolved = models.calls[0]["resolved_names"]
    assert resolved == [
        {
            "name": "downtown",
            "stored_values": [{"column": "public.real_estate_dld_transactions.area_name_en", "value": "Burj Khalifa"}],
        }
    ]


def test_an_all_zero_aggregate_is_retried_with_the_reason():
    models = _DraftRecorder(
        [
            "SELECT count(*) AS n FROM real_estate_dld_transactions WHERE area_name_en ILIKE '%Downtown%'",
            "SELECT count(*) AS n FROM real_estate_dld_transactions WHERE area_name_en = 'Burj Khalifa'",
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
    assert models.calls[1]["previous_error"] == ALL_ZERO_ROW_RETRY_REASON
    assert update["sql_rows"] == [{"n": 4091}]


def test_a_failed_retry_keeps_the_answer_it_was_retrying():
    models = _DraftRecorder(["SELECT count(*) AS n FROM real_estate_dld_transactions", "DELETE FROM x"])
    page = SqlPage(columns=["n"], rows=[{"n": 0}], truncated=False, duration_ms=1)
    update = run_sql_lookup(_sales_state(), models, lambda sql: page)
    assert update["sql_result"]["status"] == "rows"
    assert update["sql_rows"] == [{"n": 0}]


def test_the_reply_is_told_only_the_filters_the_user_gave():
    from agent.schemas.grounding import GroundedPlace
    from agent.sql.lookup import _stated_listing_filters

    search = ListingSearch(
        filters=ListingFilters(purpose="sale", price_max=2_000_000),
        places=[GroundedPlace(title="Dubai Marina")],
    )

    assert _stated_listing_filters(search) == ["purpose: sale", "price_max: 2000000.0", "place: Dubai Marina"]
    assert _stated_listing_filters(ListingSearch(filters=ListingFilters())) == []


def test_a_search_near_the_metro_keeps_listings_within_a_short_walk():
    query = build_listing_query(
        ListingSearch(filters=ListingFilters(near_station=NearStation.METRO)), limit=10, offset=0
    )
    assert "ST_DistanceSphere" in query.sql and "chatbot_ai.metro_stations" in query.sql
    assert query.params["station_kinds"] == ["metro"]
    assert query.params["station_meters"] == 1000

    tram = build_listing_query(
        ListingSearch(filters=ListingFilters(near_station="metro_or_tram", station_within_km=0.5)), limit=10, offset=0
    )
    assert tram.params["station_kinds"] == ["metro", "tram"]
    assert tram.params["station_meters"] == 500
    assert "station_kinds" not in build_listing_query(ListingSearch(filters=ListingFilters()), limit=10, offset=0).params


def test_a_station_search_widens_the_walk_before_it_drops_the_station():
    runner = _CountingRunner(totals=[0, 0, 4], ids=[1, 2, 3, 4])
    filters = ListingFilters(near_station=NearStation.METRO, station_within_km=0.5)
    result = search_listings(ListingSearch(filters=filters, places=[MARINA]), runner, limit=10, offset=0)
    assert [params.get("station_meters") for _, params in runner.calls[:3]] == [500, 2000, None]
    assert result.filters.near_station is NearStation.ANY
    assert len(result.notes) == 2 and "2 km" in result.notes[0]

    runner = _CountingRunner(totals=[0, 3], ids=[1, 2, 3])
    result = search_listings(ListingSearch(filters=filters), runner, limit=10, offset=0)
    assert result.filters.near_station is NearStation.METRO and result.filters.station_km == 2


def test_the_reply_is_told_how_close_to_a_station_in_plain_words():
    from agent.sql.lookup import _stated_listing_filters

    near = ListingSearch(filters=ListingFilters(purpose="rent", near_station=NearStation.METRO))
    assert _stated_listing_filters(near) == ["purpose: rent", "within 1 km of a metro station"]
    close = ListingSearch(filters=ListingFilters(near_station=NearStation.TRAM, station_within_km=0.5))
    assert _stated_listing_filters(close) == ["within 0.5 km of a tram stop"]


def test_golden_visa_searches_only_sales_at_the_qualifying_price():
    filters = ListingFilters.model_validate({"purpose": "rent", "golden_visa": True})
    assert filters.purpose is ListingPurpose.SALE
    query = build_listing_query(ListingSearch(filters=filters), limit=10, offset=0)
    assert query.params["purpose"] == "for_sale"
    assert "COALESCE(p.price_max, p.price_min) >= %(golden_visa_min)s" in query.sql
    assert query.params["golden_visa_min"] == GOLDEN_VISA_MIN_PRICE_AED


def test_relaxing_the_price_never_drops_below_the_golden_visa_threshold():
    runner = _CountingRunner(totals=[0, 4], ids=[1, 2])
    filters = ListingFilters(golden_visa=True, price_max=1_500_000)
    result = search_listings(ListingSearch(filters=filters, places=[MARINA]), runner, limit=10, offset=0)
    assert result.ids == ["1", "2"]
    _, page_params = runner.calls[-1]
    assert "price_max" not in page_params
    assert page_params["golden_visa_min"] == GOLDEN_VISA_MIN_PRICE_AED
    assert page_params["purpose"] == "for_sale"


def test_the_reply_is_told_the_golden_visa_condition_in_plain_words():
    from agent.sql.lookup import _stated_listing_filters

    search = ListingSearch(filters=ListingFilters(golden_visa=True))
    assert _stated_listing_filters(search) == [
        "purpose: sale",
        "qualifies for the UAE Golden Visa: for sale at AED 2,000,000 or more",
    ]


def test_an_unmatched_place_is_stated_as_a_place_not_as_how_it_was_searched():
    from agent.sql.lookup import _stated_listing_filters

    search = ListingSearch(filters=ListingFilters(), unmatched_places=["Pam Jumara"])
    assert _stated_listing_filters(search) == ["place: Pam Jumara"]


class _MetroSearchModels(_ListingModels):
    def route_query(self, **kwargs) -> QueryRoute:
        route = super().route_query(**kwargs)
        return route.model_copy(
            update={"listing_filters": route.listing_filters.model_copy(update={"near_station": NearStation.METRO})}
        )

    def draft_reply(self, **kwargs):
        from agent.schemas.reply import StructuredReply

        self.answers.append(kwargs)
        return StructuredReply(intro_text="Two homes near the metro.", show_map=True)


def test_a_search_near_the_metro_pins_each_listing_and_its_station():
    models = _MetroSearchModels()
    runner = _CountingRunner(totals=[2], ids=[101, 102])
    station_calls: list[tuple[list[int], list[str]]] = []

    def stations(ids: list[int], kinds: list[str]) -> list[dict]:
        station_calls.append((ids, kinds))
        return [
            {
                "id": 101,
                "lat": 25.0806,
                "lng": 55.1398,
                "station_kind": "metro",
                "station_name": "DAMAC Properties Metro Station",
                "station_line": "Red Metro line",
                "station_lat": 25.0799,
                "station_lng": 55.1475,
                "station_km": "0.8",
            }
        ]

    red = {"line": "Red Metro line", "path": [[25.0799, 55.1475], [25.0900, 55.1600]]}
    graph = build_chat_graph(InMemorySaver())
    events = list(
        graph.stream(
            {"messages": [HumanMessage(content="2 bed apartments for sale near the metro in marina")]},
            config={"configurable": {"thread_id": "metro-search", "user_id": "user-1"}},
            context=AgentContext(
                user_id="user-1",
                models=models,
                sql_runner=runner,
                listing_loader=lambda ids: [{"id": 101, "building_name": "Marina Gate"}, {"id": 102}],
                nearest_station_loader=stations,
                rail_line_loader=lambda: [red],
                grounding=_index(),
            ),
            stream_mode="custom",
        )
    )

    assert station_calls == [([101, 102], ["metro"])]
    assert models.answers[0]["map_available"] is True
    assert "within 1 km of a metro station" in models.answers[0]["filters"]
    place_map = next(event["reply"]["map"] for event in events if event.get("event") == "reply")
    assert [(pin["kind"], pin["label"]) for pin in place_map["pins"]] == [
        ("listing", "Marina Gate"),
        ("metro", "DAMAC Properties Metro Station"),
    ]
    assert place_map["pins"][0]["detail"] == "0.8 km to DAMAC Properties Metro Station"
    assert place_map["pins"][0]["property_id"] == "101"
    assert [line["line"] for line in place_map["lines"]] == ["red"]


def test_a_search_with_no_station_filter_looks_up_no_stations():
    models = _ListingModels()
    runner = _CountingRunner(totals=[2], ids=[101, 102])
    graph = build_chat_graph(InMemorySaver())

    def stations(ids, kinds):
        raise AssertionError("no station lookup without a station filter")

    state = graph.invoke(
        {"messages": [HumanMessage(content="2 bed properties for sale in marina")]},
        config={"configurable": {"thread_id": "no-metro", "user_id": "user-1"}},
        context=AgentContext(
            user_id="user-1",
            models=models,
            sql_runner=runner,
            listing_loader=lambda ids: [],
            nearest_station_loader=stations,
            grounding=_index(),
        ),
    )
    assert state["map_pins"] == []
