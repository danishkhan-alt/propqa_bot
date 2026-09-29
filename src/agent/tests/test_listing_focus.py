"""Asking about listings the user picked on screen: their full advert, with no routing or SQL drafting."""

from __future__ import annotations

from decimal import Decimal

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.enums.routing import Intent, Route, TurnKind
from agent.graph.nodes.reply import MISSING_LISTINGS_REPLY
from agent.graph.runner import _build_turn_input
from agent.graph.workflow import build_chat_graph
from agent.schemas.reply import StructuredReply
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute
from agent.sql.listing_details import MAX_FOCUSED_LISTINGS, fetch_focused_listings

CARDS = {
    201: {
        "id": 201,
        "title_en": "3 B/R, Harbour Gate Tower 2",
        "purpose": "for_sale",
        "show_price": True,
        "price_max": Decimal("2400000.00"),
        "rooms": 3,
        "area": Decimal("1641.00"),
        "building_name": "Harbour Gate Tower 2",
        "images": ["https://cdn.test/a.jpg"],
        "phone": "+971500000000",
    },
    368: {
        "id": 368,
        "title_en": "2 B/R, Green Community West",
        "purpose": "for_rent",
        "show_price": True,
        "rental_period": "yearly",
        "yearly_price": Decimal("95000"),
        "rooms": 2,
    },
}

DETAILS = {
    201: {
        "id": 201,
        "description": "Bright corner unit facing the park.",
        "is_free_hold": True,
        "is_parking_available": True,
        "no_of_parkings": 1,
        "is_corner": True,
        "plot_area": Decimal("0"),
        "amenities": ["Shared Pool", "Balcony or Terrace"],
        "views": ["Pool View"],
        "lat": 25.2012,
        "lng": 55.3471,
        "nearby_places": {
            "parks": [{"name": "Dubai Creek Harbor Park", "km": Decimal("0.1"), "lat": 25.2003, "lng": 55.3480}],
            "schools": [],
            "hospitals": "not a list",
        },
        "metro_station": "Creek Metro Station",
        "metro_line": "Green Metro line",
        "metro_km": Decimal("1.5"),
        "metro_lat": Decimal("25.219370"),
        "metro_lng": Decimal("55.338690"),
    },
}


def _cards(ids: list[int]) -> list[dict]:
    return [CARDS[item] for item in ids if item in CARDS]


def _details(ids: list[int]) -> list[dict]:
    return [DETAILS[item] for item in ids if item in DETAILS]


# Facts


def test_a_focused_listing_carries_its_card_and_advert_details():
    facts = fetch_focused_listings([201], _cards, _details).facts
    assert facts == [
        {
            "title": "3 B/R, Harbour Gate Tower 2",
            "bedrooms": 3,
            "size_sqft": 1641,
            "purpose": "for_sale",
            "asking_price_max_aed": 2400000,
            "building": "Harbour Gate Tower 2",
            "description": "Bright corner unit facing the park.",
            "freehold": True,
            "parking_available": True,
            "parking_spaces": 1,
            "corner_unit": True,
            "plot_size_sqft": 0,
            "amenities": ["Balcony or Terrace", "Shared Pool"],
            "views": ["Pool View"],
            "nearby_places": {"parks": [{"name": "Dubai Creek Harbor Park", "km": 0.1}]},
            "nearest_metro": {"station": "Creek Metro Station", "line": "Green Metro line", "km": 1.5},
        }
    ]


def test_a_focused_listing_pins_itself_its_metro_and_what_is_nearby():
    pins = fetch_focused_listings([201], _cards, _details).map_pins
    assert pins == [
        {
            "lat": 25.2012,
            "lng": 55.3471,
            "label": "Harbour Gate Tower 2",
            "detail": "",
            "kind": "listing",
            "property_id": "201",
        },
        {
            "lat": 25.21937,
            "lng": 55.33869,
            "label": "Creek Metro Station",
            "detail": "Green Metro line · 1.5 km away",
            "kind": "metro",
            "line": "green",
        },
        {"lat": 25.2003, "lng": 55.348, "label": "Dubai Creek Harbor Park", "detail": "0.1 km away", "kind": "nearby"},
    ]


def test_a_listing_without_a_pin_has_nothing_to_map():
    assert fetch_focused_listings([368], _cards, _details).map_pins == []


def test_listings_keep_the_order_picked_and_a_gone_listing_is_dropped():
    facts = fetch_focused_listings([368, 999, 201], _cards, _details).facts
    assert [fact["title"] for fact in facts] == ["2 B/R, Green Community West", "3 B/R, Harbour Gate Tower 2"]
    assert all("property_id" not in fact for fact in facts)
    assert facts[0]["rent_aed"] == {"amount": 95000, "period": "yearly"}
    assert "amenities" not in facts[0]


def test_a_detail_failure_still_answers_from_the_card():
    def broken(ids: list[int]) -> list[dict]:
        raise RuntimeError("warehouse down")

    facts = fetch_focused_listings([201], _cards, broken).facts
    assert facts[0]["building"] == "Harbour Gate Tower 2"
    assert "amenities" not in facts[0]


def test_no_more_listings_are_read_than_the_ui_can_attach():
    seen: list[list[int]] = []

    def record(ids: list[int]) -> list[dict]:
        seen.append(ids)
        return []

    fetch_focused_listings(list(range(1, 20)), record, record)
    assert all(len(ids) == MAX_FOCUSED_LISTINGS for ids in seen)


# Graph


class _FocusModels:
    def route_query(self, **kwargs) -> QueryRoute:
        self.routed += 1
        return QueryRoute(route=Route.DIRECT_ANSWER, turn_kind=TurnKind.NEW, confidence=0.9, rationale="Chat.")

    def stream_answer_direct(self, **kwargs):
        yield "Hello."

    def answer_direct(self, **kwargs) -> str:
        return "Hello."

    def __init__(self, *, show_map: bool = False) -> None:
        self.routed = 0
        self.drafts: list[dict] = []
        self.show_map = show_map

    def draft_listing_reply(self, **kwargs) -> StructuredReply:
        self.drafts.append(kwargs)
        kwargs["on_text"]("It is a **3-bed** in Harbour Gate Tower 2.")
        return StructuredReply(intro_text="It is a **3-bed** in Harbour Gate Tower 2.", show_map=self.show_map)


def _graph_and_context(models: _FocusModels):
    graph = build_chat_graph(InMemorySaver())
    context = AgentContext(
        user_id="user-1",
        models=models,
        listing_loader=_cards,
        listing_detail_loader=_details,
        rail_line_loader=lambda: [],
    )
    return graph, context


def test_a_question_about_picked_listings_skips_routing_and_reads_the_advert():
    models = _FocusModels()
    graph, context = _graph_and_context(models)
    config = {"configurable": {"thread_id": "focus", "user_id": "user-1"}}
    previous = LastNeedDb(domain_ids=["listings"], join_ids=[], intent_summary="2 beds in the creek")
    graph.update_state(
        config,
        {
            "last_need_db": previous,
            "query_route": QueryRoute(
                route=Route.NEED_DB, turn_kind=TurnKind.NEW, intent=Intent.LIST, confidence=0.9, rationale="Search."
            ),
            "domain_route": DomainRoute(domain_ids=["listings"], join_ids=[], confidence=0.9, rationale="Listings."),
        },
        as_node="record_search_and_clear_turn_state",
    )

    state = graph.invoke(
        _build_turn_input("Tell me about this property", focused_property_ids=[201]),
        config=config,
        context=context,
    )

    assert models.routed == 0
    assert len(models.drafts) == 1
    assert models.drafts[0]["listings"][0]["nearest_metro"]["station"] == "Creek Metro Station"
    assert state["messages"][-1].content == "It is a **3-bed** in Harbour Gate Tower 2."
    assert state["query_route"] is None
    assert state["focused_listings"] == []
    assert state["map_pins"] == []
    # The previous search is kept, so "cheaper" after this still refines it.
    assert state["last_need_db"].intent_summary == "2 beds in the creek"


def test_a_turn_without_picked_listings_goes_back_to_routing():
    models = _FocusModels()
    graph, context = _graph_and_context(models)
    config = {"configurable": {"thread_id": "focus-then-chat", "user_id": "user-1"}}

    graph.invoke(_build_turn_input("What about parking?", focused_property_ids=[201]), config=config, context=context)
    state = graph.invoke(_build_turn_input("Hi again"), config=config, context=context)

    assert models.routed == 1
    assert len(models.drafts) == 1
    assert state["focused_property_ids"] == []
    assert state["messages"][-1].content == "Hello."


def test_listings_that_are_gone_get_a_plain_reply_without_a_model_call():
    models = _FocusModels()
    graph, context = _graph_and_context(models)
    state = graph.invoke(
        {"messages": [HumanMessage(content="Tell me about these")], "focused_property_ids": [999]},
        config={"configurable": {"thread_id": "focus-gone", "user_id": "user-1"}},
        context=context,
    )
    assert models.drafts == []
    assert models.routed == 0
    assert state["messages"][-1].content == MISSING_LISTINGS_REPLY


def test_a_question_about_what_is_nearby_shows_the_listing_on_a_map():
    models = _FocusModels(show_map=True)
    graph, context = _graph_and_context(models)
    config = {"configurable": {"thread_id": "focus-map", "user_id": "user-1"}}

    events = list(
        graph.stream(
            _build_turn_input("How far is the metro?", focused_property_ids=[201]),
            config=config,
            context=context,
            stream_mode="custom",
        )
    )

    assert models.drafts[0]["map_available"] is True
    assert "lat" not in str(models.drafts[0]["listings"])
    reply = next(event["reply"] for event in events if event.get("event") == "reply")
    assert [pin["kind"] for pin in reply["map"]["pins"]] == ["listing", "metro", "nearby"]


def test_no_map_when_the_answer_does_not_ask_for_one():
    models = _FocusModels()
    graph, context = _graph_and_context(models)
    config = {"configurable": {"thread_id": "focus-no-map", "user_id": "user-1"}}

    events = list(
        graph.stream(
            _build_turn_input("Is there parking?", focused_property_ids=[201]),
            config=config,
            context=context,
            stream_mode="custom",
        )
    )

    reply = next(event["reply"] for event in events if event.get("event") == "reply")
    assert reply["map"] is None
