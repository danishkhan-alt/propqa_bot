"""Run the lookup eval against real models and the real warehouse, and score every case.

    python -m evals.run_sql_eval                 # every case
    python -m evals.run_sql_eval marina_listings # chosen cases

Prints one line per case and writes the full record (SQL, rows, reply) to logs/.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.context import AgentContext
from agent.graph.workflow import build_chat_graph
from agent.grounding import get_grounding_cache
from agent.sql.execute import fetch_reference_rows
from common.db import close_pools
from common.schemas.pagination import DEFAULT_PER_PAGE

GOLDEN_PATH = Path(__file__).resolve().parent / "sql_golden.yaml"

PLACE_LISTINGS_SQL = """
WITH RECURSIVE v2_place AS (
    SELECT id FROM public.locations_v2 WHERE lower(title_en) = ANY(%(names)s)
    UNION SELECT child.id FROM public.locations_v2 child JOIN v2_place parent ON child.parent_id = parent.id
), legacy_place AS (
    SELECT id FROM public.locations WHERE lower(name_en) = ANY(%(names)s)
    UNION SELECT child.id FROM public.locations child JOIN legacy_place parent ON child.parent_id = parent.id
)
SELECT p.id FROM public.properties p
WHERE p.status = 'active' AND p.deleted_at IS NULL
  AND (
    p.location_v2_id IN (SELECT id FROM v2_place)
    OR p.location_master_project_id IN (SELECT id FROM legacy_place)
    OR p.location_project_id IN (SELECT id FROM legacy_place)
    OR p.location_building_id IN (SELECT id FROM legacy_place)
    OR p.address_en ILIKE ANY(%(patterns)s)
  )
  AND ({where})
"""
ANY_LISTINGS_SQL = "SELECT p.id FROM public.properties p WHERE p.status = 'active' AND p.deleted_at IS NULL AND ({where})"


@dataclass
class TurnOutcome:
    """What the last turn of a case produced."""

    sql: str = ""
    status: str = ""
    rows: list[dict] = field(default_factory=list)
    listing_ids: list[str] = field(default_factory=list)
    total: int | None = None
    notes: list[str] = field(default_factory=list)
    names: list[dict] = field(default_factory=list)
    route: dict = field(default_factory=dict)
    reply: str = ""
    seconds: float = 0.0
    error: str = ""


@dataclass
class CaseScore:
    id: str
    passed: bool
    detail: str
    outcome: TurnOutcome


def main(case_ids: list[str]) -> int:
    cases = [case for case in _load_cases() if not case_ids or case["id"] in case_ids]
    if get_grounding_cache().load_now() is None:
        print("Grounding index did not load; the eval would not reflect production.")
        return 2
    scores: list[CaseScore] = []
    try:
        for case in cases:
            outcome = _run_case(case)
            score = _score(case, outcome)
            scores.append(score)
            mark = "PASS" if score.passed else "FAIL"
            print(f"{mark}  {case['id']:<32} {score.detail}  ({outcome.seconds:.1f}s)", flush=True)
    finally:
        close_pools()
    passed = sum(score.passed for score in scores)
    print(f"\n{passed}/{len(scores)} passed")
    report = Path("logs") / f"sql_eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps([asdict(score) for score in scores], indent=2, default=str), encoding="utf-8")
    print(f"Report: {report}")
    return 0 if passed == len(scores) else 1


def _load_cases() -> list[dict]:
    return list(yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"])


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
            outcome.listing_ids = [str(item) for item in value.get("listing_ids") or []]
        if node == "write_reply" and value.get("messages"):
            outcome.reply = str(value["messages"][-1].content)


def _score(case: dict, outcome: TurnOutcome) -> CaseScore:
    if outcome.error:
        return CaseScore(case["id"], False, outcome.error, outcome)
    if "listings" in case:
        passed, detail = _score_listings(case["listings"], outcome)
    elif "value" in case:
        passed, detail = _score_value(case["value"], outcome)
    elif "sql_contains" in case:
        passed, detail = _score_sql_contains(case["sql_contains"], outcome)
    else:
        passed, detail = _score_rows_contain(case["rows_contain"], outcome)
    return CaseScore(case["id"], passed, detail, outcome)


def _score_listings(expected: dict, outcome: TurnOutcome) -> tuple[bool, str]:
    truth = _truth_listing_ids(expected, expected.get("where") or "TRUE")
    relaxed = False
    if not truth and expected.get("relaxed_where"):
        truth = _truth_listing_ids(expected, expected["relaxed_where"])
        relaxed = True
    returned = set(outcome.listing_ids)
    wrong = returned - truth
    # "The cheapest penthouse" asks for one row; otherwise a page of the default size.
    page_size = outcome.route.get("limit") or DEFAULT_PER_PAGE
    expected_on_page = min(len(truth), page_size)
    total_ok = outcome.total is None or outcome.total == len(truth)
    note_ok = not relaxed or bool(outcome.notes)
    passed = not wrong and len(returned) == expected_on_page and total_ok and note_ok
    detail = (
        f"truth={len(truth)}{' (relaxed)' if relaxed else ''} returned={len(returned)} "
        f"total={outcome.total} wrong={len(wrong)}"
    )
    if relaxed and not outcome.notes:
        detail += " missing relaxation note"
    return passed, detail


def _truth_listing_ids(expected: dict, where: str) -> set[str]:
    names = [str(name).lower() for name in expected.get("place") or []]
    if names:
        sql = PLACE_LISTINGS_SQL.format(where=where)
        rows = fetch_reference_rows(sql, {"names": names, "patterns": [f"%{name}%" for name in names]})
    else:
        rows = fetch_reference_rows(ANY_LISTINGS_SQL.format(where=where))
    return {str(row["id"]) for row in rows}


def _score_value(expected: dict, outcome: TurnOutcome) -> tuple[bool, str]:
    tolerance = float(expected.get("tolerance") or 0)
    truths = [_to_float(next(iter(fetch_reference_rows(sql)[0].values()))) for sql in expected["sql"]]
    answered = [number for row in outcome.rows[:1] for number in map(_to_float, row.values()) if number is not None]
    for truth in truths:
        if truth is None:
            continue
        for number in answered:
            if abs(number - truth) <= tolerance * max(abs(truth), 1):
                return True, f"answer={number:g} truth={truth:g}"
    shown = ", ".join(f"{truth:g}" for truth in truths if truth is not None)
    return False, f"answer={answered[:3]} truth in [{shown}] status={outcome.status}"


def _score_sql_contains(texts: list[str], outcome: TurnOutcome) -> tuple[bool, str]:
    missing = [text for text in texts if text not in outcome.sql]
    return not missing and bool(outcome.rows), f"rows={len(outcome.rows)} missing_in_sql={missing}"


def _score_rows_contain(texts: list[str], outcome: TurnOutcome) -> tuple[bool, str]:
    cells = " | ".join(str(value) for row in outcome.rows for value in row.values()).lower()
    missing = [text for text in texts if text.lower() not in cells]
    return not missing and bool(outcome.rows), f"rows={len(outcome.rows)} missing={missing}"


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
