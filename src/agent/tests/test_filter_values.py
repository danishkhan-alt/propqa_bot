"""Filter values in a drafted statement: the user's spelling swapped for the stored one, and
values a column does not hold explained when nothing comes back."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from agent.enums.listing import MentionKind
from agent.schemas.grounding import GroundedName, Grounding, StoredMatch
from agent.schemas.routes import DomainRoute
from agent.schemas.sql import SqlDraft, SqlPage
from agent.sql.execute import SqlFailed
from agent.sql.filter_values import check_filter_values, explain_missing_column
from agent.sql.lookup import run_sql_lookup

SALES = "public.real_estate_dld_transactions"
AVERAGES = "public.dld_community_avg_sale_price"

MAMZAR = Grounding(
    names=[
        GroundedName(
            text="Al Mamzer",
            kind=MentionKind.PLACE,
            stored=[StoredMatch(table=SALES, column="area_name_en", value="Al Mamzar", kind="area")],
        )
    ]
)


def test_the_users_spelling_of_a_grounded_name_becomes_the_stored_value():
    checked = check_filter_values(
        f"SELECT COUNT(*) FROM {SALES} WHERE area_name_en = 'Al Mamzer' AND property_sub_type_en = 'Flat'",
        MAMZAR,
    )
    assert "area_name_en = 'Al Mamzar'" in checked.sql
    assert checked.corrections == [f"{SALES}.area_name_en: 'Al Mamzer' -> 'Al Mamzar'"]


def test_an_aliased_table_and_an_in_list_are_checked_too():
    checked = check_filter_values(
        f"SELECT COUNT(*) FROM {SALES} AS t WHERE t.area_name_en IN ('Al Mamzer', 'Marsa Dubai')",
        MAMZAR,
    )
    assert "IN ('Al Mamzar', 'Marsa Dubai')" in checked.sql


def test_a_value_outside_a_measured_list_is_reported_with_the_values_it_holds():
    checked = check_filter_values(
        f"SELECT avg_price FROM {AVERAGES} WHERE property_sub_type_en IN ('2 Bedrooms', 'Apartments') "
        "AND avg_price_type = 'rent'",
        None,
    )
    assert len(checked.problems) == 1
    assert "does not hold '2 Bedrooms'" in checked.problems[0]
    assert "'Apartments'" in checked.problems[0]
    # Reported only: the statement is unchanged and still runs.
    assert "'2 Bedrooms'" in checked.sql


def test_a_value_that_differs_only_in_case_is_corrected():
    checked = check_filter_values(f"SELECT avg_price FROM {AVERAGES} WHERE property_sub_type_en = 'villas'", None)
    assert "property_sub_type_en = 'Villas'" in checked.sql
    assert checked.problems == []


def test_a_missing_column_error_lists_the_columns_the_table_has():
    explained = explain_missing_column('column "unit_number" does not exist', f"SELECT unit_number FROM {AVERAGES}")
    assert explained.startswith('column "unit_number" does not exist')
    assert "property_sub_type_en" in explained
    assert explain_missing_column("timeout", "SELECT 1") == "timeout"


class _Drafts:
    def __init__(self, drafts: list[str]) -> None:
        self.drafts = list(drafts)
        self.calls: list[dict] = []

    def draft_sql(self, **kwargs) -> SqlDraft:
        self.calls.append(kwargs)
        return SqlDraft(sql=self.drafts[len(self.calls) - 1], purpose="rent")


def _state(grounding: Grounding | None = None) -> dict:
    return {
        "messages": [HumanMessage(content="2-bed rent in JLT")],
        "domain_route": DomainRoute(domain_ids=["market", "transactions"], join_ids=[], confidence=1, rationale="."),
        "catalog_context": "",
        "grounding": grounding,
    }


def test_an_empty_result_retries_with_the_values_the_column_holds():
    models = _Drafts(
        [
            f"SELECT avg_price FROM {AVERAGES} WHERE property_sub_type_en = '2 Bedrooms'",
            f"SELECT avg_price FROM {AVERAGES} WHERE property_sub_type_en = 'Apartments'",
        ]
    )
    pages = iter(
        [
            SqlPage(columns=["avg_price"], rows=[], truncated=False, duration_ms=1),
            SqlPage(columns=["avg_price"], rows=[{"avg_price": 90000}], truncated=False, duration_ms=1),
        ]
    )
    update = run_sql_lookup(_state(), models, lambda sql: next(pages))
    assert "does not hold '2 Bedrooms'" in models.calls[1]["previous_error"]
    assert update["sql_rows"] == [{"avg_price": 90000}]


def test_the_stored_spelling_is_what_runs():
    models = _Drafts([f"SELECT COUNT(*) AS n FROM {SALES} WHERE area_name_en = 'Al Mamzer'"])
    ran: list[str] = []

    def runner(sql: str) -> SqlPage:
        ran.append(sql)
        return SqlPage(columns=["n"], rows=[{"n": 812}], truncated=False, duration_ms=1)

    run_sql_lookup(_state(MAMZAR), models, runner)
    assert "'Al Mamzar'" in ran[0] and "'Al Mamzer'" not in ran[0]


def test_a_missing_column_retry_is_told_the_real_columns():
    models = _Drafts(
        [f"SELECT unit_number FROM {AVERAGES}", f"SELECT community_name_en FROM {AVERAGES}"]
    )
    outcomes = iter([SqlFailed('column "unit_number" does not exist'), None])

    def runner(sql: str) -> SqlPage:
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return SqlPage(columns=["community_name_en"], rows=[{"community_name_en": "Dubai Marina"}], truncated=False, duration_ms=1)

    run_sql_lookup(_state(), models, runner)
    assert "community_name_en" in models.calls[1]["previous_error"]


BROKERS = "chatbot_ai.real_estate_brokers"


def test_a_person_name_pattern_the_user_never_typed_is_removed():
    checked = check_filter_values(
        f"SELECT broker_name_en, phone FROM {BROKERS} "
        "WHERE (broker_name_en ILIKE '%hindi%' OR broker_name_en ILIKE '%singh%') AND phone IS NOT NULL",
        None,
        typed_names=["Sobha Hartland"],
    )
    assert "ILIKE" not in checked.sql
    assert "phone IS NOT NULL" in checked.sql
    assert len(checked.removed) == 2


def test_a_broker_the_user_named_is_still_filtered_on():
    sql = f"SELECT phone FROM {BROKERS} WHERE broker_name_en ILIKE '%Sofya Shamuzova%'"
    checked = check_filter_values(sql, None, typed_names=["Sofya Shamuzova"])
    assert checked.removed == []
    assert "ILIKE '%Sofya Shamuzova%'" in checked.sql


def test_a_window_counted_from_today_past_the_data_is_explained():
    checked = check_filter_values(
        f"SELECT MAX(actual_worth) FROM {SALES} WHERE instance_date >= CURRENT_DATE - INTERVAL '7 DAYS'", None
    )
    assert any("instance_date holds data only up to" in problem for problem in checked.problems)


def test_a_window_anchored_on_the_data_is_left_alone():
    checked = check_filter_values(
        f"SELECT MAX(actual_worth) FROM {SALES} WHERE instance_date >= "
        f"(SELECT MAX(instance_date) FROM {SALES}) - INTERVAL '7 DAYS'",
        None,
    )
    assert checked.problems == []


def test_a_question_the_data_cannot_answer_is_not_drafted_as_a_stand_in():
    class _Missing:
        calls = 0

        def draft_sql(self, **kwargs) -> SqlDraft:
            self.calls += 1
            return SqlDraft(sql="", purpose="ridership", missing="passenger numbers per metro station")

    def runner(sql: str) -> SqlPage:
        raise AssertionError("nothing should run")

    models = _Missing()
    update = run_sql_lookup(_state(), models, runner)
    assert models.calls == 1
    assert update["sql_result"]["status"] == "unavailable"
    assert update["sql_result"]["error"] == "passenger numbers per metro station"
