"""Read-only SQL lookup: guards, retries, and a log line that contains every returned row."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.enums.routing import Intent, Route, TurnKind
from agent.graphs.chat import build_chat_graph
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlDraft
from agent.sql.execute import SqlFailed, SqlPage, json_ready
from agent.schemas.grounding import GroundedName, Grounding, StoredMatch
from agent.sql.guard import (
    SqlRejected,
    applied_conditions,
    blended_averages,
    prepare_select,
    segment_rules,
    tables_in_domains,
)
from agent.sql.listings import listing_ids_from
from agent.sql.lookup import BLENDED_NOTE, EMPTY_LOOKUP_REPLY, FAILED_LOOKUP_REPLY, run_sql_lookup
from agent.sql.recipes import bind_recipe, recipe, recipes
from catalog import list_domains
from agent.sql.trace import trace_sql_attempt


class _Draft:
    def __init__(
        self,
        sql: str = (
            "SELECT property_sub_type_en, avg(actual_worth) AS average_price FROM real_estate_transactions "
            "WHERE trans_group_en = 'Sales' GROUP BY property_sub_type_en"
        ),
    ) -> None:
        self.sql = sql
        self.calls = 0
        self.errors: list[str | None] = []

    def draft_sql(self, **kwargs) -> SqlDraft:
        self.calls += 1
        self.errors.append(kwargs.get("previous_error"))
        return SqlDraft(sql=self.sql, purpose="average sale price")


class _Rows:
    def __init__(self, pages: list[SqlPage]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, sql: str) -> SqlPage:
        self.calls.append(sql)
        index = min(len(self.calls) - 1, len(self.pages) - 1)
        page = self.pages[index]
        if isinstance(page, Exception):
            raise page
        return page


def _state(message: str = "Average sale price in Dubai Marina") -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "domain_route": DomainRoute(
            domain_ids=["transactions"],
            join_ids=["locations"],
            confidence=1,
            rationale="Sold prices.",
        ),
        "catalog_context": "real_estate_transactions",
    }


def test_prepare_select_caps_a_catalog_query_and_rejects_the_rest():
    allowed = tables_in_domains(["transactions", "locations"])
    sql = prepare_select(
        "SELECT avg(actual_worth) AS average_price FROM real_estate_transactions",
        allowed,
        row_cap=100,
    )
    assert "real_estate_transactions" in sql.lower()
    assert "limit 101" in sql.lower()

    kept = prepare_select(
        "SELECT actual_worth FROM real_estate_transactions LIMIT 5",
        allowed,
        row_cap=100,
    )
    assert "limit 5" in kept.lower()

    with pytest.raises(SqlRejected):
        prepare_select("DELETE FROM real_estate_transactions", allowed, 100)
    with pytest.raises(SqlRejected):
        prepare_select(
            "SELECT * FROM real_estate_transactions; DROP TABLE real_estate_transactions",
            allowed,
            100,
        )
    with pytest.raises(SqlRejected):
        prepare_select("SELECT * FROM secret_table", allowed, 100)
    with pytest.raises(SqlRejected):
        prepare_select("SELECT * INTO copy FROM real_estate_transactions", allowed, 100)
    with pytest.raises(SqlRejected):
        prepare_select("SELECT 1", allowed, 100)
    with pytest.raises(SqlRejected):
        prepare_select("SELECT * FROM public.real_estate_transactions", allowed, 100)

    cte = prepare_select(
        "WITH recent AS (SELECT actual_worth FROM real_estate_transactions) SELECT * FROM recent",
        allowed,
        row_cap=10,
    )
    assert "real_estate_transactions" in cte.lower()


def test_lookup_logs_every_returned_row_and_sends_them_to_langfuse(caplog):
    caplog.set_level(logging.INFO, logger="agent.sql")
    rows = [
        {"area_name_en": "Dubai Marina", "average_price": "1650000"},
        {"area_name_en": "Dubai Marina", "average_price": "1700000"},
    ]
    runner = _Rows([SqlPage(columns=["area_name_en", "average_price"], rows=rows, truncated=False, duration_ms=4)])
    client = _FakeLangfuse()

    update = run_sql_lookup(_state(), _Draft(), runner, client=client, row_cap=100)

    assert update["sql_rows"] == rows
    assert update["sql_result"]["row_count"] == 2
    assert "limit 101" in runner.calls[0].lower()
    logged = [record.extra_data for record in caplog.records if record.message == "sql.execute"]
    assert logged[-1]["rows"] == rows
    assert logged[-1]["columns"] == ["area_name_en", "average_price"]
    assert logged[-1]["sql"]
    observation = client.observations[-1]
    assert observation["name"] == "sql.execute"
    assert observation["output"]["rows"] == rows
    assert observation["input"]["domain_ids"] == ["transactions", "locations"]


def test_an_empty_result_is_retried_once():
    runner = _Rows(
        [
            SqlPage(columns=[], rows=[], truncated=False, duration_ms=1),
            SqlPage(
                columns=["average_price"],
                rows=[{"average_price": "1650000"}],
                truncated=False,
                duration_ms=2,
            ),
        ]
    )
    draft = _Draft()
    update = run_sql_lookup(_state(), draft, runner, row_cap=100)

    assert draft.calls == 2
    assert draft.errors[1] == "The query returned no rows."
    assert update["sql_result"]["status"] == "rows"
    assert len(runner.calls) == 2


def test_applied_conditions_lists_every_filter_but_not_joins_or_presence_checks():
    sql = (
        "WITH rents AS (SELECT area_name_en, avg(annual_amount) AS rent FROM chatbot_ai.rent_contracts "
        "WHERE contract_start_date >= CURRENT_DATE - INTERVAL '2 years' AND annual_amount > 0 "
        "AND area_name_en IS NOT NULL GROUP BY 1 HAVING count(*) >= 20) "
        "SELECT r.area_name_en FROM rents r JOIN chatbot_ai.real_estate_transactions t "
        "ON t.area_name_en = r.area_name_en WHERE t.area_name_en = r.area_name_en"
    )

    assert applied_conditions(sql) == [
        "contract_start_date >= CURRENT_DATE - INTERVAL '2 YEARS'",
        "annual_amount > 0",
        "COUNT(*) >= 20",
    ]
    assert applied_conditions("not sql at all (") == []


def test_an_empty_lookup_carries_its_filters_and_the_data_span():
    draft = _Draft(
        "SELECT avg(annual_amount) AS rent FROM chatbot_ai.rent_contracts "
        "WHERE contract_start_date >= CURRENT_DATE - INTERVAL '2 years'"
    )
    runner = _Rows([SqlPage(columns=[], rows=[], truncated=False, duration_ms=1)])
    update = run_sql_lookup(_state(), draft, runner, row_cap=100)

    result = update["sql_result"]
    assert result["status"] == "empty"
    assert result["filters"] == ["contract_start_date >= CURRENT_DATE - INTERVAL '2 YEARS'"]
    spans = {span["column"]: span["covers"] for span in result["coverage"]}
    assert any("start" in column.lower() for column in spans), spans


def test_a_warehouse_failure_does_not_invent_a_number():
    runner = _Rows([SqlFailed("column average_price does not exist"), SqlFailed("column average_price does not exist")])
    update = run_sql_lookup(_state(), _Draft(), runner, row_cap=100)
    assert update["sql_result"]["status"] == "failed"
    assert update["sql_rows"] == []
    assert runner.calls and len(runner.calls) == 2


def _value(result) -> dict:
    value = getattr(result, "value", result)
    return value if isinstance(value, dict) else dict(value)


def test_graph_answers_from_the_rows_and_does_not_keep_them(caplog):
    caplog.set_level(logging.INFO, logger="agent.sql")
    rows = [{"area_name_en": "Dubai Marina", "average_price": "1650000"}]
    runner = _Rows([SqlPage(columns=["area_name_en", "average_price"], rows=rows, truncated=True, duration_ms=3)])
    models = _GraphModels()
    graph = build_chat_graph(InMemorySaver())
    result = graph.invoke(
        {"messages": [HumanMessage(content="Average sale price in Dubai Marina")]},
        config={"configurable": {"thread_id": "t-sql"}},
        context=AgentContext(user_id="user-1", models=models, sql_runner=runner),
        version="v2",
    )
    state = _value(result)
    assert "1650000" in state["messages"][-1].content
    assert state.get("sql_result") is None
    assert state.get("sql_rows") in (None, [])
    assert state["last_need_db"].result_meta["truncated"] is True
    logged = [record.extra_data["rows"] for record in caplog.records if record.message == "sql.execute"]
    assert rows in logged


def test_graph_says_nothing_matched_without_calling_the_answer_model():
    runner = _Rows(
        [
            SqlPage(columns=[], rows=[], truncated=False, duration_ms=1),
            SqlPage(columns=[], rows=[], truncated=False, duration_ms=1),
        ]
    )
    models = _GraphModels()
    graph = build_chat_graph(InMemorySaver())
    result = graph.invoke(
        {"messages": [HumanMessage(content="Average sale price in Dubai Marina")]},
        config={"configurable": {"thread_id": "t-empty-sql"}},
        context=AgentContext(user_id="user-1", models=models, sql_runner=runner),
        version="v2",
    )
    state = _value(result)
    assert state["messages"][-1].content == EMPTY_LOOKUP_REPLY
    assert models.answer_calls == 0


def test_graph_hides_a_database_error():
    runner = _Rows([SqlFailed("password=secret"), SqlFailed("password=secret")])
    models = _GraphModels()
    graph = build_chat_graph(InMemorySaver())
    result = graph.invoke(
        {"messages": [HumanMessage(content="Average sale price in Dubai Marina")]},
        config={"configurable": {"thread_id": "t-fail-sql"}},
        context=AgentContext(user_id="user-1", models=models, sql_runner=runner),
        version="v2",
    )
    state = _value(result)
    reply = state["messages"][-1].content
    assert reply == FAILED_LOOKUP_REPLY
    assert "password" not in reply
    assert "1650000" not in reply


def test_json_ready_keeps_money_exact():
    assert json_ready(Decimal("1650000.50")) == "1650000.50"
    assert json_ready(date(2026, 1, 2)) == "2026-01-02"


class _GraphModels:
    def __init__(self) -> None:
        self.answer_calls = 0

    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            confidence=0.9,
            rationale="Sold prices.",
        )

    def route_domain(self, **kwargs) -> DomainRoute:
        return DomainRoute(
            domain_ids=["transactions"],
            join_ids=["locations"],
            confidence=0.9,
            rationale="Sold prices.",
        )

    def answer_direct(self, **kwargs) -> str:
        return "hello"

    def answer_unavailable(self, **kwargs) -> str:
        return "unavailable"

    def draft_sql(self, **kwargs) -> SqlDraft:
        return SqlDraft(
            sql="SELECT avg(actual_worth) AS average_price FROM real_estate_transactions",
            purpose="average sale price",
        )

    def answer_from_sql(self, **kwargs) -> str:
        self.answer_calls += 1
        return f"The average sale price is {kwargs['rows'][0]['average_price']} AED."


class _FakeObservation:
    def __init__(self, parent: dict) -> None:
        self.parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, **kwargs):
        self.parent["output"] = kwargs.get("output")
        self.parent["level"] = kwargs.get("level")


class _FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[dict] = []

    def start_as_current_observation(self, **kwargs):
        record = dict(kwargs)
        self.observations.append(record)
        return _FakeObservation(record)


def test_a_listing_list_keeps_only_property_ids():
    state = _state("Show me apartments")
    state["query_route"] = QueryRoute(
        route=Route.NEED_DB,
        turn_kind=TurnKind.NEW,
        intent=Intent.LIST,
        confidence=1,
        rationale="Show apartments.",
    )
    state["domain_route"] = DomainRoute(
        domain_ids=["listings"],
        join_ids=["locations"],
        confidence=1,
        rationale="Inventory.",
    )
    rows = [
        {"property_id": Decimal("15802.0"), "project_name_en": "Marina Gate"},
        {"property_id": 19806, "project_name_en": "Creek Tower"},
        {"building_id": 589050, "community_name_english": "Al Murar"},
    ]
    assert listing_ids_from(state, rows) == ["15802", "19806", "589050"]

    state["query_route"] = QueryRoute(
        route=Route.NEED_DB,
        turn_kind=TurnKind.NEW,
        intent=Intent.AGGREGATE,
        confidence=1,
        rationale="Average price.",
    )
    assert listing_ids_from(state, rows) == []


def test_trace_survives_a_langfuse_outage():
    class Boom:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("langfuse down")

    trace_sql_attempt(
        {
            "sql": "SELECT 1",
            "purpose": "lookup",
            "domain_ids": ["transactions"],
            "attempt": 1,
            "columns": ["n"],
            "rows": [{"n": 1}],
            "row_count": 1,
            "truncated": False,
            "duration_ms": 1,
            "error": None,
            "status": "rows",
        },
        Boom(),
    )


def test_rows_that_are_live_listings_become_listing_cards_on_any_intent():
    state = _state("Check property 7952")
    state["query_route"] = QueryRoute(
        route=Route.NEED_DB, turn_kind=TurnKind.NEW, intent=Intent.LOOKUP, confidence=1, rationale="One listing."
    )
    state["domain_route"] = DomainRoute(domain_ids=["listings"], join_ids=[], confidence=1, rationale="Listing.")
    rows = [{"property_id": 7952, "title_en": "Marina flat", "permit_number": None}]
    sql = "SELECT p.id AS property_id, p.title_en, p.permit_number FROM public.properties AS p WHERE p.id = 7952"
    assert listing_ids_from(state, rows, sql) == ["7952"]


def test_a_dld_property_id_is_not_a_listing():
    state = _state("Sales of unit 55")
    state["query_route"] = QueryRoute(
        route=Route.NEED_DB, turn_kind=TurnKind.NEW, intent=Intent.LOOKUP, confidence=1, rationale="DLD unit."
    )
    rows = [{"property_id": 55, "amount": 1000000}]
    assert listing_ids_from(state, rows, "SELECT t.property_id, t.amount FROM dld.transactions t") == []
    assert listing_ids_from(state, rows, "SELECT avg(p.price_max) AS property_id FROM public.properties p") == []


# Kinds of property and fixed recipes


def test_an_average_must_not_mix_kinds_of_property():
    rules = segment_rules(["transactions", "market"])
    mixed = blended_averages(
        "SELECT area_name_en, avg(actual_worth) FROM real_estate_transactions WHERE trans_group_en = 'Sales' "
        "GROUP BY area_name_en",
        rules,
    )
    assert len(mixed) == 1 and "property_sub_type_en" in mixed[0]
    assert "trans_group_en" in blended_averages(
        "SELECT property_sub_type_en, avg(actual_worth) FROM real_estate_transactions GROUP BY 1", rules
    )[0]
    # A presence check is not a split; filtering to the kind the user named is.
    assert blended_averages(
        "SELECT avg(sale_price) FROM public.price_trend_buy_fact WHERE rooms_en IS NOT NULL", rules
    )
    assert not blended_averages(
        "SELECT avg(sale_price) FROM public.price_trend_buy_fact WHERE rooms_en = '2 B/R'", rules
    )
    # A grouping reached through a CTE alias counts, and so does a median.
    assert not blended_averages(
        "WITH s AS (SELECT rooms_en AS layout, sale_price FROM public.price_trend_buy_fact) "
        "SELECT CASE WHEN layout = 'Studio' THEN 0 ELSE 1 END AS beds, "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY sale_price) FROM s GROUP BY 1",
        rules,
    )
    assert blended_averages(
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY sale_price) FROM public.price_trend_buy_fact", rules
    )
    # Counts and totals are not averages.
    assert not blended_averages("SELECT count(*) FROM real_estate_transactions", rules)


def test_every_declared_segment_is_a_column_of_its_table_or_a_join():
    joined = {"category_id"}
    for rule in set(segment_rules([domain["id"] for domain in list_domains()]).values()):
        for column in (*rule.segments, *rule.basis):
            assert column in rule.columns or column in joined, (rule.table, column)


def test_a_blended_draft_is_redrafted_once_then_answered_with_a_note():
    blended = "SELECT avg(actual_worth) AS average_price FROM real_estate_transactions"
    page = SqlPage(columns=["average_price"], rows=[{"average_price": "1650000"}], truncated=False, duration_ms=1)
    runner = _Rows([page])
    draft = _Draft(blended)
    update = run_sql_lookup(_state(), draft, runner, row_cap=100)

    assert draft.calls == 2
    assert "mixes kinds of property" in draft.errors[1]
    assert len(runner.calls) == 1
    assert update["sql_result"]["status"] == "rows"
    assert BLENDED_NOTE in update["sql_result"]["notes"]


def test_an_aggregate_filter_is_not_reported_as_a_condition():
    sql = (
        "SELECT count(*) FILTER (WHERE recent) FROM public.price_trend_buy_fact "
        "WHERE master_project_en = 'Dubai Marina'"
    )
    assert applied_conditions(sql) == ["master_project_en = 'Dubai Marina'"]


def _grounded(*values: str, table: str = "public.price_trend_buy_fact", kind: str = "master_project"):
    return Grounding(
        names=[
            GroundedName(
                text=value,
                kind="place",
                stored=[StoredMatch(table=table, column="master_project_en", value=value, kind=kind)],
            )
            for value in values
        ]
    )


def test_a_recipe_binds_only_the_names_it_takes():
    overview = recipe("dubai_market_overview")
    community = recipe("community_sale_prices_by_bedrooms")
    assert bind_recipe(overview, Grounding()) is not None
    assert bind_recipe(overview, _grounded("Dubai Marina")) is None
    assert bind_recipe(community, Grounding()) is None
    assert bind_recipe(community, _grounded("Dubai Marina", "Business Bay")) is None
    assert bind_recipe(community, _grounded("Dubai Marina", kind="community")) is None

    bound = bind_recipe(community, _grounded("Jumeirah Village Circle"))
    assert "ANY(ARRAY['Jumeirah Village Circle'])" in bound.sql
    assert bound.filters() == ["place: Jumeirah Village Circle"]
    quoted = bind_recipe(community, _grounded("O'Hara Gardens"))
    assert "ARRAY['O''Hara Gardens']" in quoted.sql


def test_every_recipe_passes_the_guard_and_splits_kinds_of_property():
    for item in recipes().values():
        grounding = _grounded("Dubai Marina") if item.params else Grounding()
        bound = bind_recipe(item, grounding)
        guarded = prepare_select(bound.sql, tables_in_domains(list(item.domains)), 100)
        assert blended_averages(guarded, segment_rules(list(item.domains))) == [], item.id


def test_a_chosen_recipe_answers_without_drafting_sql():
    state = _state("How are prices in JVC?")
    state["domain_route"] = DomainRoute(
        domain_ids=["market"], join_ids=[], recipe_id="community_sale_prices_by_bedrooms", confidence=1, rationale="Trend."
    )
    state["grounding"] = _grounded("Jumeirah Village Circle")
    page = SqlPage(columns=["bedrooms", "median_price_aed"], rows=[{"bedrooms": "1-bed", "median_price_aed": 1069300}], truncated=False, duration_ms=3)
    runner = _Rows([page])
    draft = _Draft()
    update = run_sql_lookup(state, draft, runner, row_cap=100)

    assert draft.calls == 0
    assert update["sql_result"]["recipe"] == "community_sale_prices_by_bedrooms"
    assert update["sql_result"]["filters"] == ["place: Jumeirah Village Circle"]
    assert "Jumeirah Village Circle" in runner.calls[0]


def test_a_recipe_that_finds_nothing_falls_back_to_a_draft():
    state = _state("How are prices in JVC?")
    state["domain_route"] = DomainRoute(
        domain_ids=["market", "transactions"],
        join_ids=[],
        recipe_id="community_sale_prices_by_bedrooms",
        confidence=1,
        rationale="Trend.",
    )
    state["grounding"] = _grounded("Jumeirah Village Circle")
    empty = SqlPage(columns=[], rows=[], truncated=False, duration_ms=1)
    found = SqlPage(columns=["average_price"], rows=[{"average_price": "1"}], truncated=False, duration_ms=1)
    runner = _Rows([empty, found])
    draft = _Draft()
    update = run_sql_lookup(state, draft, runner, row_cap=100)

    assert draft.calls == 1
    assert "recipe" not in update["sql_result"]
    assert update["sql_result"]["status"] == "rows"


def test_an_or_that_escapes_the_other_filters_is_sent_back():
    allowed = tables_in_domains(["market"])
    with pytest.raises(SqlRejected, match="parentheses"):
        prepare_select(
            "SELECT annual_rent FROM public.price_trend_rent_fact WHERE master_project_en = 'Dubai Marina' "
            "AND property_sub_type_en ILIKE '%bed%' OR property_sub_type_en = 'Studio'",
            allowed,
            100,
        )
    kept = prepare_select(
        "SELECT annual_rent FROM public.price_trend_rent_fact WHERE master_project_en = 'Dubai Marina' "
        "AND (property_sub_type_en ILIKE '%bed%' OR property_sub_type_en = 'Studio')",
        allowed,
        100,
    )
    assert "OR" in kept
