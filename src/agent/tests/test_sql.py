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
from agent.sql.guard import SqlRejected, applied_conditions, prepare_select, tables_in_domains
from agent.sql.listings import listing_ids_from
from agent.sql.lookup import EMPTY_LOOKUP_REPLY, FAILED_LOOKUP_REPLY, run_sql_lookup
from agent.sql.trace import trace_sql_attempt


class _Draft:
    def __init__(self, sql: str = "SELECT avg(actual_worth) AS average_price FROM real_estate_transactions") -> None:
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
