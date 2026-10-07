from __future__ import annotations

from pathlib import Path

import httpx
import openai
import pytest
import yaml
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.enums.routing import Intent, Route, TurnKind
from agent.graph.nodes.catalog import load_domain_catalog
from agent.graph.nodes.turn_end import record_search_and_clear_turn_state
from agent.graph.nodes.reply import OUT_OF_SCOPE_REPLY
from agent.graph.workflow import build_chat_graph
from agent.schemas.listing import NameMention
from agent.schemas.routes import (
    DomainRoute,
    QueryRoute,
    as_assumptions,
    as_domain_route,
    as_last_need_db,
    as_query_route,
)
from agent.schemas.sql import SqlDraft, SqlPage
from agent.services.llm.calls import invoke_structured_with_fallback
from agent.services.llm.providers import is_openai_reasoning_model
from agent.validator import sanitize_domain_route, sanitize_query_route

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "router_golden.yaml"


class ScriptedModels:
    def __init__(self) -> None:
        self.query_calls = 0
        self.domain_calls = 0
        self.answer_calls = 0
        self.last_turn_kind: TurnKind | None = None

    def route_query(self, **kwargs) -> QueryRoute:
        self.query_calls += 1
        message = kwargs["message"].lower()
        if "python" in message:
            return QueryRoute(
                route=Route.OUT_OF_SCOPE,
                turn_kind=TurnKind.NEW,
                confidence=0.95,
                rationale="Asks for code.",
            )
        if "schools" in message:
            return QueryRoute(
                route=Route.NEED_DB,
                turn_kind=TurnKind.PIVOT,
                confidence=0.9,
                rationale="Same place, different subject.",
            )
        if "cheaper" in message:
            return QueryRoute(
                route=Route.NEED_DB,
                turn_kind=TurnKind.REFINE,
                purpose="rent",
                limit=25,
                confidence=0.9,
                rationale="Same lookup, tighter price.",
            )
        if "show me properties" in message or "show me agents" in message:
            return QueryRoute(
                route=Route.NEED_DB,
                turn_kind=TurnKind.NEW,
                intent=Intent.LIST,
                confidence=0.9,
                rationale="A list with no purpose and no count.",
            )
        if "for rent" in message:
            return QueryRoute(
                route=Route.NEED_DB,
                turn_kind=TurnKind.NEW,
                purpose="rent",
                confidence=0.9,
                rationale="The user asked for rent.",
            )
        if "marina" in message or "price" in message:
            return QueryRoute(
                route=Route.NEED_DB,
                turn_kind=TurnKind.NEW,
                purpose="sale",
                confidence=0.9,
                rationale="Sold prices.",
            )
        return QueryRoute(
            route=Route.DIRECT_ANSWER,
            turn_kind=TurnKind.NEW,
            confidence=0.95,
            rationale="Greeting.",
        )

    def route_domain(self, **kwargs) -> DomainRoute:
        self.domain_calls += 1
        self.last_turn_kind = kwargs["turn_kind"]
        if kwargs["turn_kind"] is TurnKind.PIVOT:
            return DomainRoute(
                domain_ids=["schools"],
                join_ids=["locations"],
                confidence=0.9,
                rationale="Nearby schools.",
            )
        return DomainRoute(
            domain_ids=["transactions"],
            join_ids=["locations"],
            confidence=0.92,
            rationale="Sold prices.",
        )

    def answer_direct(self, **kwargs) -> str:
        self.answer_calls += 1
        return "I can explain property terms and look up Dubai market data."

    def answer_unavailable(self, **kwargs) -> str:
        self.answer_calls += 1
        asked = kwargs["message"].strip()
        return f"I don't have enough information about {asked}. If you want, we can look at the area around it."

    def draft_sql(self, **kwargs) -> SqlDraft:
        bare = [name for name in kwargs.get("allowed_tables") or [] if "." not in name]
        table = bare[0] if bare else "real_estate_dld_transactions"
        return SqlDraft(sql=f"SELECT * FROM {table}", purpose="lookup")

    def answer_from_sql(self, **kwargs) -> str:
        self.answer_calls += 1
        self.last_sql_rows = list(kwargs["rows"])
        value = next(iter(kwargs["rows"][0].values()))
        return f"The average sale price is {value} AED."


def _fixture_sql():
    def run(sql: str) -> SqlPage:
        del sql
        return SqlPage(
            columns=["average_price"],
            rows=[{"average_price": "1650000"}],
            truncated=False,
            duration_ms=1,
        )

    return run


def _turn(graph, message: str, thread_id: str, models: ScriptedModels, runner=None) -> dict:
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)]},
        config={"configurable": {"thread_id": thread_id}},
        context=AgentContext(
            user_id="user-1",
            models=models,
            sql_runner=runner or _fixture_sql(),
        ),
        version="v2",
    )
    value = getattr(result, "value", result)
    return value if isinstance(value, dict) else dict(value)


def test_graph_declines_an_out_of_scope_request_without_a_model_reply():
    models = ScriptedModels()
    state = _turn(
        build_chat_graph(InMemorySaver()),
        "Give me python code for a rate limiter for Dubai properties",
        "t-off-topic",
        models,
    )
    assert state["messages"][-1].content == OUT_OF_SCOPE_REPLY
    assert models.domain_calls == 0
    assert models.answer_calls == 0


def test_graph_routes_a_greeting_without_the_domain_router():
    models = ScriptedModels()
    state = _turn(build_chat_graph(InMemorySaver()), "Hi, what can you help with?", "t-hi", models)

    route = as_query_route(state["query_route"])
    assert route is not None
    assert route.route is Route.DIRECT_ANSWER
    assert models.query_calls == 1
    assert models.domain_calls == 0
    assert models.answer_calls == 1
    assert state["messages"][-1].content.startswith("I can explain")
    assert state.get("catalog_context", "") == ""
    assert state["awaiting_sql"] is False


def test_price_question_follows_the_model_into_a_lookup():
    models = ScriptedModels()
    state = _turn(
        build_chat_graph(InMemorySaver()),
        "Average sale price in Dubai Marina last 12 months",
        "t-price",
        models,
    )

    route = as_query_route(state["query_route"])
    domain = as_domain_route(state["domain_route"])
    assert route is not None and route.route is Route.NEED_DB
    assert domain is not None
    assert domain.domain_ids == ["transactions"]
    assert domain.join_ids == ["locations"]
    assert state["awaiting_sql"] is False
    assert state["catalog_context"] == ""
    assert state.get("sql_result") is None
    assert "1650000" in state["messages"][-1].content
    assert as_last_need_db(state["last_need_db"]).domain_ids == ["transactions"]
    assert models.answer_calls == 1
    assert models.last_sql_rows == [{"average_price": "1650000"}]


def test_refine_reuses_domains_when_the_model_says_refine():
    models = ScriptedModels()
    graph = build_chat_graph(InMemorySaver())
    _turn(graph, "Average sale price in Dubai Marina last 12 months", "t-refine", models)
    state = _turn(graph, "cheaper", "t-refine", models)

    route = as_query_route(state["query_route"])
    domain = as_domain_route(state["domain_route"])
    assumptions = as_assumptions(state["assumptions"])
    assert route is not None and route.turn_kind is TurnKind.REFINE
    assert domain is not None and domain.domain_ids == ["transactions"]
    assert assumptions is not None and assumptions.purpose == "rent" and assumptions.limit == 25
    assert models.query_calls == 2
    assert models.domain_calls == 1


def test_new_subject_on_a_follow_up_pivots_and_re_routes_domains():
    models = ScriptedModels()
    graph = build_chat_graph(InMemorySaver())
    _turn(graph, "Average sale price in Dubai Marina last 12 months", "t-pivot", models)
    state = _turn(graph, "schools near those", "t-pivot", models)

    route = as_query_route(state["query_route"])
    domain = as_domain_route(state["domain_route"])
    assert route is not None and route.turn_kind is TurnKind.PIVOT
    assert domain is not None and domain.domain_ids == ["schools"]
    assert models.last_turn_kind is TurnKind.PIVOT


def test_empty_message_is_routed_by_the_model():
    models = ScriptedModels()
    state = _turn(build_chat_graph(InMemorySaver()), "   ", "t-empty", models)

    route = as_query_route(state["query_route"])
    reply = state["messages"][-1].content
    assert route is not None and route.route is Route.DIRECT_ANSWER
    assert models.query_calls == 1
    assert models.answer_calls == 1
    assert reply.startswith("I can explain")


def test_unknown_domain_asks_instead_of_loading_a_catalog():
    class Unknown(ScriptedModels):
        def route_query(self, **kwargs) -> QueryRoute:
            self.query_calls += 1
            return QueryRoute(route=Route.NEED_DB, turn_kind=TurnKind.NEW, confidence=0.9, rationale="Lookup.")

        def route_domain(self, **kwargs) -> DomainRoute:
            self.domain_calls += 1
            return DomainRoute(domain_ids=["not_a_domain"], join_ids=[], confidence=0.5, rationale="Invented.")

    models = Unknown()
    state = _turn(build_chat_graph(InMemorySaver()), "Tell me about zoning appeals", "t-unknown", models)
    route = as_query_route(state["query_route"])
    assert route is not None and route.route is Route.NEED_DB
    reply = state["messages"][-1].content
    assert "zoning appeals" in reply
    assert models.answer_calls == 1
    assert "dataset" not in reply.lower()
    assert state["catalog_context"] == ""


def test_catalog_yaml_is_loaded_for_the_turn_and_not_kept():
    state = {
        "messages": [HumanMessage(content="Average sale price in Dubai Marina")],
        "query_route": QueryRoute(route=Route.NEED_DB, turn_kind=TurnKind.NEW, confidence=1, rationale="Lookup."),
        "domain_route": DomainRoute(
            domain_ids=["transactions"],
            join_ids=["locations"],
            confidence=1,
            rationale="Sold prices.",
        ),
    }
    loaded = load_domain_catalog(state)
    assert "real_estate_dld_transactions" in loaded["catalog_context"]
    assert "# join: locations" in loaded["catalog_context"]
    final = record_search_and_clear_turn_state({**state, **loaded}, {"configurable": {"thread_id": "t-catalog"}})
    assert final["catalog_context"] == ""
    assert final["loaded_domains"] == []
    assert final["last_need_db"].domain_ids == ["transactions"]


def test_sanitize_drops_unknown_ids_and_caps_packs():
    route = DomainRoute(
        domain_ids=["listings", "schools", "rta", "amenities", "made_up"],
        join_ids=[],
        confidence=0.8,
        rationale="Too many.",
    )
    cleaned, notes = sanitize_domain_route(route)
    assert cleaned.domain_ids == ["listings", "schools", "rta"]
    assert cleaned.join_ids == []
    assert "dropped_unknown" in notes
    assert "truncated_primary" in notes


def test_low_confidence_is_logged_and_the_model_route_stands():
    route = QueryRoute(
        route=Route.DIRECT_ANSWER,
        turn_kind=TurnKind.NEW,
        confidence=0.2,
        rationale="Unsure.",
    )
    updated, notes = sanitize_query_route(route, None)
    assert updated.route is Route.DIRECT_ANSWER
    assert "low_confidence" in notes


def test_a_list_uses_the_shared_page_and_does_not_invent_a_purpose():
    models = ScriptedModels()
    graph = build_chat_graph(InMemorySaver())

    properties = as_assumptions(
        _turn(graph, "Show me properties", "t-properties", models)["assumptions"]
    )
    agents = as_assumptions(_turn(graph, "Show me agents", "t-agents", models)["assumptions"])

    assert properties is not None and agents is not None
    assert properties.purpose is None and agents.purpose is None
    assert properties.page == agents.page == 1
    assert properties.limit == agents.limit == 10


def test_stated_purpose_is_kept_as_the_model_set_it():
    models = ScriptedModels()
    state = _turn(build_chat_graph(InMemorySaver()), "apartments for rent near a metro", "t-rent", models)

    assumptions = as_assumptions(state["assumptions"])
    assert assumptions is not None
    assert assumptions.purpose == "rent"
    assert assumptions.limit is None


def test_structured_output_retries_once_then_uses_the_fallback():
    class Boom:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, messages, config=None):
            self.calls += 1
            raise ValueError("bad json")

    runnable = Boom()
    fallback = QueryRoute(route=Route.NEED_DB, turn_kind=TurnKind.NEW, confidence=0.3, rationale="Fallback.")
    parsed = invoke_structured_with_fallback(runnable, [], None, fallback)
    assert parsed is fallback
    assert runnable.calls == 2


def _status_error(status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.APIStatusError("error", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize(("status", "calls"), [(400, 1), (401, 1), (408, 2), (429, 2), (500, 2)])
def test_a_rejected_request_is_not_sent_twice(status: int, calls: int):
    class Rejected:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, messages, config=None):
            self.calls += 1
            raise _status_error(status)

    runnable = Rejected()
    fallback = QueryRoute(route=Route.NEED_DB, turn_kind=TurnKind.NEW, confidence=0.3, rationale="Fallback.")
    assert invoke_structured_with_fallback(runnable, [], None, fallback) is fallback
    assert runnable.calls == calls


def test_golden_file_is_model_routed():
    cases = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    assert {case["id"] for case in cases} >= {"empty", "cheaper", "greeting", "average_price"}
    assert all(case["deterministic"] is False for case in cases)


def _schema_counts(node, counts=None) -> dict:
    counts = counts if counts is not None else {"unions": 0, "optional": 0}
    if isinstance(node, dict):
        counts["unions"] += "anyOf" in node
        if isinstance(node.get("properties"), dict):
            counts["optional"] += len(set(node["properties"]) - set(node.get("required", [])))
        for value in node.values():
            _schema_counts(value, counts)
    elif isinstance(node, list):
        for value in node:
            _schema_counts(value, counts)
    return counts


def test_the_router_schema_stays_inside_the_structured_output_limits():
    # The API rejects more than 16 union-typed or 24 optional fields, and optional fields
    # slow grammar compilation, so every field is required and unions stay under the cap.
    from agent.services.llm.output_schema import build_strict_output_schema

    counts = _schema_counts(build_strict_output_schema(QueryRoute))
    assert counts["optional"] == 0
    assert counts["unions"] <= 16


def test_a_reply_of_the_wrong_shape_is_retried_then_replaced():
    # A model not held to the schema once wrapped its answer in the schema's own "properties".
    class Wrapped:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, messages, config=None):
            self.calls += 1
            if self.calls == 1:
                return {"parsed": {"properties": {"domain_ids": ["listings"]}}, "parsing_error": None}
            return {
                "parsed": {"domain_ids": ["listings"], "join_ids": [], "confidence": 0.9, "rationale": "ok"},
                "parsing_error": None,
            }

    runnable = Wrapped()
    parsed = invoke_structured_with_fallback(runnable, [], None, DomainRoute(domain_ids=[], confidence=0.3, rationale="Fallback."))
    assert isinstance(parsed, DomainRoute) and parsed.domain_ids == ["listings"]
    assert runnable.calls == 2


def test_router_schemas_are_accepted_by_strict_mode():
    # Strict mode needs closed objects and no keywords beside a $ref.
    from agent.services.llm.output_schema import build_strict_output_schema

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert set(node) == {"$ref"}
            if isinstance(node.get("properties"), dict):
                assert node["additionalProperties"] is False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for model in (QueryRoute, DomainRoute):
        walk(build_strict_output_schema(model))


def test_a_chosen_recipe_loads_its_own_pack_and_an_unknown_one_is_dropped():
    route = DomainRoute(
        domain_ids=["transactions"],
        join_ids=[],
        recipe_id="community_sale_prices_by_bedrooms",
        confidence=0.9,
        rationale="Community trend.",
    )
    cleaned, _ = sanitize_domain_route(route)
    assert cleaned.domain_ids == ["market", "transactions"]
    assert cleaned.recipe_id == "community_sale_prices_by_bedrooms"

    invented, notes = sanitize_domain_route(route.model_copy(update={"recipe_id": "made_up"}))
    assert invented.recipe_id is None
    assert invented.domain_ids == ["transactions"]
    assert "dropped_unknown_recipe" in notes


@pytest.mark.parametrize(
    "model, reasons",
    [("gpt-5.5", True), ("gpt-5.4-mini", True), ("o4-mini", True), ("gpt-5-chat-latest", False), ("gpt-4.1", False), ("gpt-4o", False)],
)
def test_only_reasoning_models_are_sent_an_effort(model, reasons):
    assert is_openai_reasoning_model(model) is reasons


def test_the_city_itself_is_never_a_place_to_filter_on():
    route = QueryRoute(
        route=Route.NEED_DB,
        turn_kind=TurnKind.NEW,
        names=[NameMention(text="Dubai"), NameMention(text=" dubai  UAE"), NameMention(text="Dubai Marina")],
        confidence=0.9,
        rationale="Trend.",
    )
    updated, notes = sanitize_query_route(route, None)
    assert [name.text for name in updated.names] == ["Dubai Marina"]
    assert "dropped_region_name" in notes
