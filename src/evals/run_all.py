"""Run the router, domain, and lookup evals and write one report.

    python -m evals.run_all
    python -m evals.run_all --split holdout
    python -m evals.run_all --split holdout --case marina_listings_typo
    python -m evals.run_all --split holdout --write-baseline

Exit 1 when a must_pass case fails, or when holdout result correctness is more
than 2 points below src/evals/baseline.json. Exit 2 when the lookup eval cannot
load the grounding index. Latency, fallback rate, cost, and the share of
data-backed replies with an ungrounded number are printed and do not change
the exit code. Cost is null until a run records token spend.
"""

from __future__ import annotations

import argparse
import sys

from config import ActiveConfig
from evals.cases import DOMAIN_PATH, ROUTER_PATH, SQL_PATH, load_suite, select_cases
from evals.langfuse_run import record_dataset_run
from evals.report import (
    EvalRow,
    build_report,
    exit_code,
    format_summary,
    grounding_summary,
    load_baseline,
    write_baseline,
    write_report,
)
from evals.run_domain_eval import evaluate as evaluate_domain
from evals.run_router_eval import evaluate as evaluate_router
from evals.run_sql_eval import CaseScore, evaluate as evaluate_sql


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("train", "val", "holdout"))
    parser.add_argument("--case", action="append", default=None)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.write_baseline and args.split != "holdout":
        print("The baseline is the holdout run. Pass --split holdout --write-baseline.")
        return 2

    router_cases = select_cases(load_suite(ROUTER_PATH), split=args.split, case_ids=args.case)
    domain_cases = select_cases(load_suite(DOMAIN_PATH), split=args.split, case_ids=args.case)
    sql_cases = select_cases(load_suite(SQL_PATH), split=args.split, case_ids=args.case)

    router_rows = evaluate_router(router_cases, quiet=True)
    domain_rows = _domain_rows(domain_cases)
    status, sql_scores = evaluate_sql(sql_cases, quiet=True)
    if status == 2:
        print("Grounding index did not load; the eval would not reflect production.")
        return 2

    report = build_report(
        args.split,
        [*router_rows, *domain_rows, *_sql_rows(sql_scores)],
        answer_grounding=grounding_summary(sql_scores),
    )
    path = write_report(report)
    _configure_stdio()
    print(format_summary(report))
    for row in report["cases"]:
        if not row["passed"]:
            print(row["detail"])
    print(f"Report: {path}")
    record_dataset_run(report)

    code = exit_code(report, load_baseline() if args.split == "holdout" else None)
    if args.write_baseline:
        # The file is this run's measurement. The exit code is the gate.
        print(f"Baseline: {write_baseline(report)}")
    if code == 1 and report["must_pass_failures"]:
        print("Blocked: must_pass failed: " + ", ".join(report["must_pass_failures"]))
    elif code == 1:
        print("Blocked: holdout result correctness dropped by more than 2 points.")
    return code


def _configure_stdio() -> None:
    """Windows consoles default to cp1252, and a reply can contain an arrow."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            return


def _domain_rows(cases: list[dict]) -> list[EvalRow]:
    router = ActiveConfig.DOMAIN_ROUTER if ActiveConfig.DOMAIN_ROUTER in {"jev", "llm"} else "llm"
    rows = evaluate_domain(cases, [router], quiet=True)[router]
    return [
        EvalRow(
            suite="domain",
            id=row["id"],
            passed=row["passed"],
            detail=row["sentence"],
            must_pass=row["must_pass"],
            split=row["split"],
            latency_s=row["latency"],
            fallback=row["fallback"],
        )
        for row in rows
    ]


def _sql_rows(scores: list[CaseScore]) -> list[EvalRow]:
    return [
        EvalRow(
            suite="sql",
            id=score.id,
            passed=score.passed,
            detail=score.detail,
            must_pass=score.must_pass,
            split=score.split,
            latency_s=score.outcome.seconds,
            fallback=score.fallback,
        )
        for score in scores
    ]


if __name__ == "__main__":
    sys.exit(main())
