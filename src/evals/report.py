"""One JSON report for a router, domain, and lookup run.

A must_pass miss blocks the run. So does a holdout result-correctness drop of
more than two points against the saved baseline. Latency, fallback rate, and
cost are recorded and never block on their own.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.cases import BASELINE_PATH

# Result correctness is stored as a percentage. Two points is the gate.
CORRECTNESS_DROP_LIMIT = 2.0


@dataclass
class EvalRow:
    """One scored case, in the shape every suite reports."""

    suite: str
    id: str
    passed: bool
    detail: str
    must_pass: bool
    split: str
    latency_s: float = 0.0
    fallback: bool = False


def sentence(case_id: str, passed: bool, detail: str) -> str:
    """A pass or fail a person can act on, starting with the case id."""
    mark = "PASS" if passed else "FAIL"
    text = detail.strip()
    if text.startswith("PASS ") or text.startswith("FAIL "):
        return text
    return f"{mark} {case_id}: {text}"


def percent(passed: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(100.0 * passed / total, 2)


def build_report(split: str | None, rows: list[EvalRow]) -> dict[str, Any]:
    by_suite = {"router": [], "domain": [], "sql": []}
    for row in rows:
        by_suite[row.suite].append(row)
    metrics = {
        "route_accuracy": percent(sum(row.passed for row in by_suite["router"]), len(by_suite["router"])),
        "domain_accuracy": percent(sum(row.passed for row in by_suite["domain"]), len(by_suite["domain"])),
        "result_correctness": percent(sum(row.passed for row in by_suite["sql"]), len(by_suite["sql"])),
    }
    counts = {
        suite: {"passed": sum(row.passed for row in suite_rows), "total": len(suite_rows)}
        for suite, suite_rows in by_suite.items()
    }
    failures = [row.id for row in rows if row.must_pass and not row.passed]
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "split": split or "all",
        "metrics": metrics,
        "counts": counts,
        "latency_s": _latency(rows),
        "fallback_rate": _fallback_rate(rows),
        "cost_usd": None,
        "must_pass_failures": failures,
        "cases": [asdict(row) for row in rows],
    }


def exit_code(report: dict[str, Any], baseline: dict[str, Any] | None) -> int:
    """1 when a must_pass case failed or holdout correctness fell by more than two points."""
    if report.get("must_pass_failures"):
        return 1
    current = (report.get("metrics") or {}).get("result_correctness")
    previous = None if not baseline else (baseline.get("metrics") or {}).get("result_correctness")
    if current is None or previous is None:
        return 0
    if previous - current > CORRECTNESS_DROP_LIMIT:
        return 1
    return 0


def load_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.is_file():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_report(report: dict[str, Any], directory: Path | None = None) -> Path:
    folder = directory or Path("logs")
    folder.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"eval_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def write_baseline(report: dict[str, Any]) -> Path:
    BASELINE_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return BASELINE_PATH


def format_summary(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    counts = report["counts"]
    lines = [
        _metric_line("route accuracy", metrics["route_accuracy"], counts["router"]),
        _metric_line("domain accuracy", metrics["domain_accuracy"], counts["domain"]),
        _metric_line("result correctness", metrics["result_correctness"], counts["sql"]),
        _side_line(report),
    ]
    failures = report["must_pass_failures"]
    if failures:
        lines.append("must_pass failures: " + ", ".join(failures))
    else:
        lines.append("must_pass failures: none")
    return "\n".join(lines)


def _metric_line(label: str, score: float | None, count: dict[str, int]) -> str:
    shown = "n/a" if score is None else f"{score:.1f}"
    return f"{label}: {shown} ({count['passed']}/{count['total']})"


def _side_line(report: dict[str, Any]) -> str:
    latency = report["latency_s"]
    mean = "n/a" if latency["mean"] is None else f"{latency['mean']:.2f}s"
    p50 = "n/a" if latency["p50"] is None else f"{latency['p50']:.2f}s"
    fallback = report["fallback_rate"]
    fallback_shown = "n/a" if fallback is None else f"{fallback:.1%}"
    cost = "n/a" if report["cost_usd"] is None else f"{report['cost_usd']}"
    return f"latency mean {mean} p50 {p50} | fallback {fallback_shown} | cost {cost}"


def _latency(rows: list[EvalRow]) -> dict[str, float | None]:
    times = sorted(row.latency_s for row in rows)
    if not times:
        return {"mean": None, "p50": None}
    return {
        "mean": round(sum(times) / len(times), 3),
        "p50": round(times[len(times) // 2], 3),
    }


def _fallback_rate(rows: list[EvalRow]) -> float | None:
    if not rows:
        return None
    return round(sum(row.fallback for row in rows) / len(rows), 4)
