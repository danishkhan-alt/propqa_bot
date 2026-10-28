"""Run the lookup eval against real models and the real warehouse, and score every case.

    python -m evals.run_sql_eval                 # every case
    python -m evals.run_sql_eval marina_listings # chosen cases
    python -m evals.run_sql_eval --split holdout

Prints one line per case and writes the full record (SQL, rows, reply, fact sheet) to logs/.
Listing cases are also checked against an independent truth set and a fact sheet, and the
reply is checked for unsupported claims.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.graph.workflow import build_chat_graph
from agent.grounding import get_grounding_cache
from agent.services.llm.fallbacks import REPLY_FALLBACK
from agent.sql.execute import fetch_reference_rows
from common.db import close_pools
from evals.cases import SQL_PATH, load_suite, select_cases
from evals.listing_facts import fetch_fact_sheet, fetch_truth_ids
from evals.listing_justification import judge_listing_reply
from evals.listing_score import TurnOutcome, score_listing_result
from evals.report import sentence


@dataclass
class CaseScore:
    id: str
    passed: bool
    detail: str
    outcome: TurnOutcome
    facts: list[dict] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    must_pass: bool = False
    split: str = ""
    fallback: bool = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_ids", nargs="*")
    parser.add_argument("--split", choices=("train", "val", "holdout"))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    cases = select_cases(load_suite(SQL_PATH), split=args.split, case_ids=args.case_ids)
    status, scores = evaluate(cases)
    if status == 2:
        print("Grounding index did not load; the eval would not reflect production.")
        return 2
    passed = sum(score.passed for score in scores)
    print(f"\n{passed}/{len(scores)} passed")
    report = Path("logs") / f"sql_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps([asdict(score) for score in scores], indent=2, default=str), encoding="utf-8")
    print(f"Report: {report}")
    return 0 if scores and passed == len(scores) else (0 if not scores else 1)


def evaluate(cases: list[dict], *, quiet: bool = False) -> tuple[int, list[CaseScore]]:
    """Score every case. Status 2 means the grounding index did not load, so nothing ran."""
    if not cases:
        return 0, []
    if get_grounding_cache().load_now() is None:
        return 2, []
    scores: list[CaseScore] = []
    try:
        for case in cases:
            try:
                outcome = _run_case(case)
                score = _score(case, outcome)
            except Exception as exc:
                outcome = TurnOutcome(error=f"{type(exc).__name__}: {exc}"[:300])
                score = _score(case, outcome)
            scores.append(score)
            if not quiet:
                mark = "PASS" if score.passed else "FAIL"
                print(f"{mark}  {case['id']:<32} {score.detail}  ({outcome.seconds:.1f}s)", flush=True)
    finally:
        close_pools()
    return 0, scores


def _run_case(case: dict) -> TurnOutcome:
    # In memory only: the eval never writes to the chatbot database.
    graph = build_chat_graph(InMemorySaver())
    thread = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
    turns = case.get("turns") or [case["message"]]
    outcome = TurnOutcome()
    for message in turns:
        outcome = TurnOutcome()
        started = time.perf_counter()
        try:
            for update in graph.stream(
                {"messages": [HumanMessage(content=message)]},
                config={"configurable": {"thread_id": thread, "user_id": "eval"}},
                context=AgentContext(user_id="eval"),
                stream_mode="updates",
            ):
                _record_node_update(update, outcome)
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"[:300]
        outcome.seconds = time.perf_counter() - started
    return outcome


def _record_node_update(update: dict, outcome: TurnOutcome) -> None:
    for node, value in update.items():
        if not isinstance(value, dict):
            continue
        if node == "choose_query_route" and value.get("query_route") is not None:
            query = value["query_route"]
            outcome.route = query.model_dump(
                mode="json", include={"intent", "purpose", "limit", "names", "listing_filters"}
            )
        if node == "choose_data_domains" and value.get("domain_route") is not None:
            outcome.route["domains"] = [*value["domain_route"].domain_ids, *value["domain_route"].join_ids]
        if node == "resolve_mentioned_names" and value.get("grounding") is not None:
            outcome.names = [
                {"text": name.text, "place": name.place.title if name.place else None, "stored": len(name.stored)}
                for name in value["grounding"].names
            ]
        if node == "run_warehouse_lookup":
            result = value.get("sql_result") or {}
            outcome.sql = str(result.get("sql") or "")
            outcome.status = str(result.get("status") or "")
            outcome.rows = list(result.get("rows") or [])
            outcome.total = result.get("total")
            outcome.notes = list(result.get("notes") or [])
            outcome.filters = [str(item) for item in (result.get("filters") or [])]
            outcome.listing_ids = [str(item) for item in value.get("listing_ids") or []]
        if node == "write_reply" and value.get("messages"):
            outcome.reply = str(value["messages"][-1].content)


def _score(case: dict, outcome: TurnOutcome) -> CaseScore:
    if outcome.error:
        return _finish(case, False, f"the turn failed before a score: {outcome.error}", outcome)
    if "listings" in case:
        return _score_listings(case, outcome)
    if "value" in case:
        passed, detail = _score_value(case["value"], outcome)
    elif "sql_contains" in case:
        passed, detail = _score_sql_contains(case["sql_contains"], outcome)
    else:
        passed, detail = _score_rows_contain(case["rows_contain"], outcome)
    return _finish(case, passed, detail, outcome)


def _finish(case: dict, passed: bool, detail: str, outcome: TurnOutcome, **extra) -> CaseScore:
    return CaseScore(
        case["id"],
        passed,
        sentence(case["id"], passed, detail),
        outcome,
        must_pass=bool(case.get("must_pass")),
        split=str(case.get("split") or ""),
        fallback=outcome.reply.strip() == REPLY_FALLBACK.intro_text.strip(),
        **extra,
    )


def _score_listings(case: dict, outcome: TurnOutcome) -> CaseScore:
    expected = case["listings"]
    where = expected.get("where") or "TRUE"
    truth = fetch_truth_ids(expected, where)
    relaxed = False
    if not truth and expected.get("relaxed_where"):
        where = expected["relaxed_where"]
        truth = fetch_truth_ids(expected, where)
        relaxed = True
    facts = fetch_fact_sheet(outcome.listing_ids, expected, where)
    claims = _justify(case, outcome, facts)
    passed, detail = score_listing_result(
        expected, outcome, truth, relaxed=relaxed, facts=facts, unsupported_claims=claims
    )
    return _finish(case, passed, detail, outcome, facts=facts, unsupported_claims=claims)


def _justify(case: dict, outcome: TurnOutcome, facts: list[dict]) -> list[str]:
    turns = case.get("turns") or [case.get("message") or ""]
    try:
        return judge_listing_reply(
            message=str(turns[-1]),
            reply=outcome.reply,
            filters=outcome.filters,
            notes=outcome.notes,
            facts=facts,
        )
    except Exception as exc:
        return [f"justification check failed: {type(exc).__name__}"]


def _score_value(expected: dict, outcome: TurnOutcome) -> tuple[bool, str]:
    tolerance = float(expected.get("tolerance") or 0)
    truths = [_to_float(next(iter(fetch_reference_rows(sql)[0].values()))) for sql in expected["sql"]]
    answered = [number for row in outcome.rows[:1] for number in map(_to_float, row.values()) if number is not None]
    for truth in truths:
        if truth is None:
            continue
        for number in answered:
            if abs(number - truth) <= tolerance * max(abs(truth), 1):
                return True, f"the answered figure {number:g} is within tolerance of the truth query {truth:g}."
    shown = ", ".join(f"{truth:g}" for truth in truths if truth is not None)
    return False, (
        f"the lookup answered {answered[:3]} but the truth query returned [{shown}] "
        f"(status {outcome.status or 'none'})."
    )


def _score_sql_contains(texts: list[str], outcome: TurnOutcome) -> tuple[bool, str]:
    missing = [text for text in texts if text not in outcome.sql]
    if missing or not outcome.rows:
        return False, (
            f"the statement is missing {missing or 'a returned row'} "
            f"and returned {len(outcome.rows)} rows."
        )
    return True, f"the statement contains the required text and returned {len(outcome.rows)} rows."


def _score_rows_contain(texts: list[str], outcome: TurnOutcome) -> tuple[bool, str]:
    cells = " | ".join(str(value) for row in outcome.rows for value in row.values()).lower()
    missing = [text for text in texts if text.lower() not in cells]
    if missing or not outcome.rows:
        return False, f"the rows are missing {missing or 'any cell'} ({len(outcome.rows)} rows)."
    return True, f"the rows contain the required text ({len(outcome.rows)} rows)."


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
