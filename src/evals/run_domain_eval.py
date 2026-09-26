"""Run the domain router eval against real routers, and compare them case by case.

    python -m evals.run_domain_eval                  # jev and llm, every case
    python -m evals.run_domain_eval --router jev     # one router
    python -m evals.run_domain_eval where_is pivot_schools

A case passes when the lead, the primary set, the joins, and the recipe all match.
The route is sanitized first, as the graph does.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml

from agent.enums.routing import TurnKind
from agent.schemas.routes import DomainRoute, LastNeedDb
from agent.services.catalog_prompt_text import render_domain_index
from agent.services.llm.models import LangChainAgentModels
from agent.sql.recipes import recipe_index_text
from agent.validator import sanitize_domain_route

GOLDEN_PATH = Path(__file__).resolve().parent / "domain_router_golden.yaml"
CHECKS = ("lead", "domains", "joins", "recipe")


def score_route(case: dict, route: DomainRoute) -> dict[str, bool]:
    expected = list(case["domains"])
    leads = {expected[0], *(case.get("accept_lead") or [])}
    lead = route.domain_ids[0] if route.domain_ids else None
    result = {
        "lead": lead in leads,
        "domains": set(route.domain_ids) == set(expected),
        "joins": "joins" not in case or set(route.join_ids) == set(case["joins"]),
        "recipe": route.recipe_id == case.get("recipe"),
    }
    return result


def run_router_cases(router: str, cases: list[dict]) -> list[dict]:
    models = LangChainAgentModels(domain_router=router)
    rows: list[dict] = []
    for case in cases:
        last = LastNeedDb.model_validate(case["last_need_db"]) if case.get("last_need_db") else None
        started = time.perf_counter()
        route = models.route_domain(
            message=case["message"],
            turn_kind=TurnKind(case.get("turn_kind", "new")),
            last_need_db=last,
            index_text=render_domain_index(),
            recipes_text=recipe_index_text(),
        )
        latency = time.perf_counter() - started
        route, _ = sanitize_domain_route(route)
        checks = score_route(case, route)
        rows.append({"id": case["id"], "route": route, "checks": checks, "latency": latency})
        mark = "PASS" if all(checks.values()) else "FAIL " + ",".join(k for k, ok in checks.items() if not ok)
        # Jev's rationale names it; anything else means Jev failed and the router model answered.
        if router == "jev" and not route.rationale.startswith("Jev"):
            mark += " (fell back)"
        print(
            f"[{router}] {case['id']:<28} {mark:<24} {latency:5.2f}s  "
            f"domains={route.domain_ids} joins={route.join_ids} recipe={route.recipe_id}"
        )
    return rows


def format_router_summary(router: str, rows: list[dict]) -> str:
    total = len(rows)
    parts = [f"{check} {sum(r['checks'][check] for r in rows)}/{total}" for check in CHECKS]
    passed = sum(all(r["checks"].values()) for r in rows)
    latencies = sorted(r["latency"] for r in rows)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    return f"{router}: pass {passed}/{total} | " + " | ".join(parts) + f" | p50 {p50:.2f}s p95 {p95:.2f}s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="*")
    parser.add_argument("--router", choices=("jev", "llm"), action="append")
    args = parser.parse_args()

    cases = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]
    if args.case_ids:
        cases = [case for case in cases if case["id"] in args.case_ids]
    routers = args.router or ["jev", "llm"]
    results = {router: run_router_cases(router, cases) for router in routers}
    print()
    for router, rows in results.items():
        print(format_router_summary(router, rows))


if __name__ == "__main__":
    main()
