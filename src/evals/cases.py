"""Load the golden files and keep the frozen split intact.

Holdout cases are the only ones that can block a release. They are never
returned for prompt optimisation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

EVALS_DIR = Path(__file__).resolve().parent
ROUTER_PATH = EVALS_DIR / "router_golden.yaml"
DOMAIN_PATH = EVALS_DIR / "domain_router_golden.yaml"
SQL_PATH = EVALS_DIR / "sql_golden.yaml"
BASELINE_PATH = EVALS_DIR / "baseline.json"

SPLITS = ("train", "val", "holdout")
TAG_KEYS = ("domain", "kind", "hard")


def load_suite(path: Path) -> list[dict]:
    """A golden file is either a list of cases or a mapping with a `cases` list."""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return list(loaded)
    return list(loaded["cases"])


def select_cases(cases: list[dict], *, split: str | None = None, case_ids: list[str] | None = None) -> list[dict]:
    """Keep cases in the requested split, then the requested ids. Omitted means all."""
    chosen = cases
    if split is not None:
        if split not in SPLITS:
            raise ValueError(f"split must be one of {', '.join(SPLITS)}")
        chosen = [case for case in chosen if case.get("split") == split]
    if case_ids:
        wanted = set(case_ids)
        chosen = [case for case in chosen if case["id"] in wanted]
    return chosen


def cases_for_optimization(cases: list[dict]) -> list[dict]:
    """Train and val only. Holdout is never shown to a prompt optimiser."""
    return [case for case in cases if case.get("split") in {"train", "val"}]


def validate_cases(cases: list[dict]) -> None:
    """Every case carries the frozen fields the runners and the gate read."""
    seen: set[str] = set()
    for case in cases:
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            raise ValueError(f"missing or repeated case id: {case_id!r}")
        seen.add(case_id)
        if case.get("split") not in SPLITS:
            raise ValueError(f"{case_id} split must be one of {', '.join(SPLITS)}")
        tags = case.get("tags")
        if not isinstance(tags, dict) or any(key not in tags for key in TAG_KEYS):
            raise ValueError(f"{case_id} tags need domain, kind, and hard")
        if not isinstance(case.get("must_pass"), bool):
            raise ValueError(f"{case_id} must_pass must be true or false")
