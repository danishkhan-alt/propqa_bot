"""Score the query router against router_golden.yaml with the production model call.

    python -m evals.run_router_eval
    python -m evals.run_router_eval --split holdout
    python -m evals.run_router_eval definition code_request

Route and turn kind are an exact match. The call is LangChainAgentModels.route_query,
then the same sanitize step the graph runs.
"""

from __future__ import annotations

import argparse
import sys
import time

from agent.schemas.routes import LastNeedDb
from agent.services.catalog_prompt_text import render_domain_blurbs
from agent.services.llm.fallbacks import QUERY_ROUTE_FALLBACK
from agent.services.llm.models import LangChainAgentModels
from agent.sql.listing_search import property_type_names
from agent.validator import sanitize_query_route
from evals.cases import ROUTER_PATH, load_suite, select_cases
from evals.report import EvalRow, sentence
from evals.router_score import score_query_case


def evaluate(cases: list[dict], *, quiet: bool = False) -> list[EvalRow]:
    if not cases:
        return []
    models = LangChainAgentModels()
    blurbs = render_domain_blurbs()
    types = property_type_names()
    rows: list[EvalRow] = []
    for case in cases:
        last = LastNeedDb.model_validate(case["last_need_db"]) if case.get("last_need_db") else None
        started = time.perf_counter()
        try:
            route = models.route_query(
                message=case["message"],
                history=str(case.get("history") or ""),
                last_need_db=last,
                domain_blurbs=blurbs,
                memory_context=str(case.get("memory_context") or ""),
                property_types=types,
            )
            route, _notes = sanitize_query_route(route, last, case["message"], {})
            latency = time.perf_counter() - started
            passed, detail = score_query_case(case, route)
            fallback = route.rationale == QUERY_ROUTE_FALLBACK.rationale
        except Exception as exc:
            latency = time.perf_counter() - started
            passed = False
            detail = sentence(case["id"], False, f"the turn failed before a score: {type(exc).__name__}: {exc}"[:300])
            fallback = False
        row = EvalRow(
            suite="router",
            id=case["id"],
            passed=passed,
            detail=detail,
            must_pass=bool(case.get("must_pass")),
            split=str(case.get("split") or ""),
            latency_s=latency,
            fallback=fallback,
        )
        rows.append(row)
        if not quiet:
            print(f"{detail}  ({latency:.1f}s)", flush=True)
    passed_count = sum(row.passed for row in rows)
    if not quiet:
        print(f"\n{passed_count}/{len(rows)} passed")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="*")
    parser.add_argument("--split", choices=("train", "val", "holdout"))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    cases = select_cases(load_suite(ROUTER_PATH), split=args.split, case_ids=args.case_ids)
    rows = evaluate(cases)
    return 0 if all(row.passed for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
