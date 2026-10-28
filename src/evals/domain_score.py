"""Score one domain-router decision against a golden case. No model call."""

from __future__ import annotations

from evals.report import sentence


def score_route(case: dict, route) -> tuple[dict[str, bool], str]:
    """Booleans for each check, plus one sentence naming what missed.

    `route` is a DomainRoute: domain_ids, join_ids, and recipe_id.
    """
    expected = list(case["domains"])
    leads = {expected[0], *(case.get("accept_lead") or [])}
    domain_ids = list(route.domain_ids)
    join_ids = list(route.join_ids)
    lead = domain_ids[0] if domain_ids else None
    checks = {
        "lead": lead in leads,
        "domains": set(domain_ids) == set(expected),
        "joins": "joins" not in case or set(join_ids) == set(case["joins"]),
        "recipe": route.recipe_id == case.get("recipe"),
    }
    got = f"domains={domain_ids} joins={join_ids} recipe={route.recipe_id}"
    if all(checks.values()):
        return checks, sentence(case["id"], True, f"lead, domains, joins, and recipe match ({got}).")
    missed = [name for name, ok in checks.items() if not ok]
    expected_bits = f"expected domains={expected}"
    if "joins" in case:
        expected_bits += f" joins={list(case['joins'])}"
    expected_bits += f" recipe={case.get('recipe')}"
    detail = f"{', '.join(missed)} did not match. Got {got}. {expected_bits}."
    return checks, sentence(case["id"], False, detail)
