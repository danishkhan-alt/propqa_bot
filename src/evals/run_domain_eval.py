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

from agent.enums.routing import TurnKind
from agent.schemas.routes import LastNeedDb
from agent.services.catalog_prompt_text import render_domain_index
from agent.services.llm.fallbacks import DOMAIN_ROUTE_FALLBACK
from agent.services.llm.models import LangChainAgentModels
from agent.sql.recipes import recipe_index_text
from agent.validator import sanitize_domain_route
from evals.cases import DOMAIN_PATH, load_suite, select_cases
from evals.domain_score import score_route
from evals.report import sentence

CHECKS = ("lead", "domains", "joins", "recipe")


def run_router_cases(router: str, cases: list[dict], *, quiet: bool = False) -> list[dict]:
    models = LangChainAgentModels(domain_router=router)
    rows: list[dict] = []
    for case in cases:
        last = LastNeedDb.model_validate(case["last_need_db"]) if case.get("last_need_db") else None
        started = time.perf_counter()
        try:
            route = models.route_domain(
                message=case["message"],
                turn_kind=TurnKind(case.get("turn_kind", "new")),
                last_need_db=last,
                index_text=render_domain_index(),
                recipes_text=recipe_index_text(),
            )
            latency = time.perf_counter() - started
            route, _ = sanitize_domain_route(route)
            checks, detail = score_route(case, route)
            fallback = _fell_back(router, route.rationale)
            passed = all(checks.values())
        except Exception as exc:
            latency = time.perf_counter() - started
            checks = {name: False for name in CHECKS}
            passed = False
            detail = sentence(case["id"], False, f"the turn failed before a score: {type(exc).__name__}: {exc}"[:300])
            fallback = True
            route = None
        rows.append(
            {
                "id": case["id"],
                "route": route,
                "checks": checks,
                "latency": latency,
                "sentence": detail,
                "passed": all(checks.values()),
                "must_pass": bool(case.get("must_pass")),
                "split": str(case.get("split") or ""),
                "fallback": fallback,
            }
        )
        if quiet:
            continue
        mark = "PASS" if all(checks.values()) else "FAIL " + ",".join(k for k, ok in checks.items() if not ok)
        # Jev's rationale names it; anything else means Jev failed and the router model answered.
        if fallback and router == "jev":
            mark += " (fell back)"
        if route is None:
            print(f"[{router}] {case['id']:<28} {mark:<24} {latency:5.2f}s  {detail}")
            continue
        print(
            f"[{router}] {case['id']:<28} {mark:<24} {latency:5.2f}s  "
            f"domains={route.domain_ids} joins={route.join_ids} recipe={route.recipe_id}"
        )
        if not all(checks.values()):
            print(f"         {detail}")
    return rows


def evaluate(cases: list[dict], routers: list[str], *, quiet: bool = False) -> dict[str, list[dict]]:
    """Score each router. The caller prints; this returns the rows."""
    return {router: run_router_cases(router, cases, quiet=quiet) for router in routers}


def _fell_back(router: str, rationale: str) -> bool:
    if rationale == DOMAIN_ROUTE_FALLBACK.rationale:
        return True
    return router == "jev" and not rationale.startswith("Jev")


def format_router_summary(router: str, rows: list[dict]) -> str:
    total = len(rows)
    if total == 0:
        return f"{router}: pass 0/0"
    parts = [f"{check} {sum(r['checks'][check] for r in rows)}/{total}" for check in CHECKS]
    passed = sum(all(r["checks"].values()) for r in rows)
    latencies = sorted(r["latency"] for r in rows)
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    fallbacks = sum(row["fallback"] for row in rows)
    return (
        f"{router}: pass {passed}/{total} | " + " | ".join(parts)
        + f" | p50 {p50:.2f}s p95 {p95:.2f}s | fallback {fallbacks}/{total}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="*")
    parser.add_argument("--router", choices=("jev", "llm"), action="append")
    parser.add_argument("--split", choices=("train", "val", "holdout"))
    args = parser.parse_args()

    cases = select_cases(load_suite(DOMAIN_PATH), split=args.split, case_ids=args.case_ids)
    routers = args.router or ["jev", "llm"]
    results = evaluate(cases, routers)
    print()
    for router, rows in results.items():
        print(format_router_summary(router, rows))


if __name__ == "__main__":
    main()
