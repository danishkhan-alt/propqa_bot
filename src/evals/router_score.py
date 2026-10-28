"""Score one query-router decision against a golden case. No model call."""

from __future__ import annotations

from evals.report import sentence


def score_query_case(case: dict, route) -> tuple[bool, str]:
    """Route and turn kind must match. Names, limit, and filters count once a case labels them.

    `route` is a QueryRoute.
    """
    problems: list[str] = []
    got_route = route.route.value
    expected_route = case["expect_route"]
    if got_route != expected_route:
        problems.append(f"route is {got_route}, expected {expected_route}")

    expected_kind = case.get("expect_turn_kind") or "new"
    got_kind = route.turn_kind.value
    if got_kind != expected_kind:
        problems.append(f"turn kind is {got_kind}, expected {expected_kind}")

    if "expect_limit" in case and route.limit != case["expect_limit"]:
        problems.append(f"limit is {route.limit}, expected {case['expect_limit']}")
    if "expect_purpose" in case and (route.purpose or None) != case["expect_purpose"]:
        problems.append(f"purpose is {route.purpose}, expected {case['expect_purpose']}")
    if "expect_names" in case:
        got_names = [name.text for name in route.names]
        if got_names != list(case["expect_names"]):
            problems.append(f"names are {got_names}, expected {list(case['expect_names'])}")

    if problems:
        detail = ". ".join(problems) + f". rationale: {route.rationale}"
        return False, sentence(case["id"], False, detail)
    detail = f"route {got_route} and turn kind {got_kind} match."
    return True, sentence(case["id"], True, detail)
