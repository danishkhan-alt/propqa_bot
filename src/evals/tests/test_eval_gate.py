"""The eval gate, the frozen split, and the failure sentences. No model and no warehouse."""

import json
from types import SimpleNamespace

from evals.cases import (
    DOMAIN_PATH,
    ROUTER_PATH,
    SQL_PATH,
    cases_for_optimization,
    load_suite,
    select_cases,
    validate_cases,
)
from evals.domain_score import score_route
from evals.report import EvalRow, build_report, exit_code, sentence
from evals.router_score import score_query_case

MUST_PASS = {
    "definition",
    "code_request",
    "show_properties",
    "cheaper",
    "marina_listings",
    "marina_listings_typo",
    "jvc_two_bed_sale_under_budget",
    "downtown_not_jebel_ali",
    "refine_keeps_place",
    "listings_sale_budget",
    "average_sale_price_period",
    "schools_near_community",
    "where_is",
    "pivot_schools",
    "market_overview",
}


def _all_cases() -> list[dict]:
    return load_suite(ROUTER_PATH) + load_suite(DOMAIN_PATH) + load_suite(SQL_PATH)


def test_every_case_has_a_frozen_split_and_tags():
    cases = _all_cases()
    validate_cases(cases)
    assert {case["id"] for case in cases if case["must_pass"]} == MUST_PASS
    assert all(case["split"] == "holdout" for case in cases if case["must_pass"])


def test_holdout_is_kept_out_of_the_optimisation_set():
    cases = _all_cases()
    trainable = cases_for_optimization(cases)
    assert "marina_listings" not in {case["id"] for case in trainable}
    assert "definition" not in {case["id"] for case in trainable}
    assert "code_request" not in {case["id"] for case in trainable}
    assert all(case["split"] in {"train", "val"} for case in trainable)
    holdout = select_cases(load_suite(SQL_PATH), split="holdout")
    assert {case["id"] for case in holdout} >= {"marina_listings", "downtown_not_jebel_ali"}


def _query(route: str, turn_kind: str, rationale: str):
    return SimpleNamespace(
        route=SimpleNamespace(value=route),
        turn_kind=SimpleNamespace(value=turn_kind),
        limit=None,
        purpose=None,
        names=[],
        rationale=rationale,
    )


def test_router_score_names_a_wrong_route_and_turn_kind():
    passed, detail = score_query_case(
        {"id": "definition", "expect_route": "direct_answer"},
        _query("need_db", "refine", "Look it up."),
    )
    assert not passed
    assert detail.startswith("FAIL definition:")
    assert "route is need_db, expected direct_answer" in detail
    assert "turn kind is refine, expected new" in detail


def test_router_score_passes_when_the_route_and_turn_kind_match():
    passed, detail = score_query_case(
        {"id": "code_request", "expect_route": "out_of_scope", "expect_turn_kind": "new"},
        _query("out_of_scope", "new", "Asks for code."),
    )
    assert passed
    assert detail.startswith("PASS code_request:")


def _domain(domain_ids, join_ids, recipe_id):
    return SimpleNamespace(domain_ids=domain_ids, join_ids=join_ids, recipe_id=recipe_id)


def test_domain_score_names_the_check_that_missed():
    case = {
        "id": "average_sale_price_period",
        "domains": ["transactions"],
        "joins": ["locations"],
        "recipe": None,
    }
    checks, detail = score_route(case, _domain(["listings"], [], None))
    assert checks["lead"] is False
    assert checks["domains"] is False
    assert checks["joins"] is False
    assert detail.startswith("FAIL average_sale_price_period:")
    assert "lead, domains, joins" in detail
    assert "expected domains=['transactions']" in detail


def test_domain_score_passes_when_every_check_matches():
    checks, detail = score_route(
        {
            "id": "average_sale_price_period",
            "domains": ["transactions"],
            "joins": ["locations"],
            "recipe": None,
        },
        _domain(["transactions"], ["locations"], None),
    )
    assert all(checks.values())
    assert detail.startswith("PASS average_sale_price_period:")


def test_a_must_pass_miss_blocks_and_a_plain_miss_does_not():
    blocked = build_report(
        "holdout",
        [EvalRow("sql", "marina_listings", False, "FAIL marina_listings: wrong area.", True, "holdout")],
    )
    assert exit_code(blocked, None) == 1
    open_miss = build_report(
        "holdout",
        [EvalRow("sql", "palm_penthouses", False, "FAIL palm_penthouses: short page.", False, "holdout")],
    )
    assert exit_code(open_miss, None) == 0


def test_result_correctness_blocks_only_after_a_drop_of_more_than_two_points():
    report = build_report(
        "holdout",
        [
            EvalRow("sql", "a", True, "PASS a: ok.", False, "holdout"),
            EvalRow("sql", "b", False, "FAIL b: wrong figure.", False, "holdout"),
        ],
    )
    # 50, against a baseline of 53, is a 3 point drop.
    assert exit_code(report, {"metrics": {"result_correctness": 53}}) == 1
    assert exit_code(report, {"metrics": {"result_correctness": 51.5}}) == 0
    assert report["metrics"]["result_correctness"] == 50.0
    assert report["cost_usd"] is None


def test_failure_sentences_keep_an_existing_mark():
    assert sentence("marina_listings", False, "3 of 10 listings are outside Dubai Marina.") == (
        "FAIL marina_listings: 3 of 10 listings are outside Dubai Marina."
    )
    already = "FAIL marina_listings: already written."
    assert sentence("marina_listings", False, already) == already


def test_report_round_trip_keeps_the_three_scores(tmp_path):
    report = build_report("holdout", [EvalRow("router", "definition", True, "PASS definition: ok.", True, "holdout")])
    path = tmp_path / "eval.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["metrics"]["route_accuracy"] == 100.0
    assert loaded["metrics"]["result_correctness"] is None
    assert loaded["must_pass_failures"] == []
