"""Record an eval run in Langfuse when the process has keys. A missing client is a skip."""

from __future__ import annotations

from agent.services.tracing import get_langfuse_client
from common.logger import get_logger

logger = get_logger("evals")

DATASET_NAME = "propqa-eval"


def record_dataset_run(report: dict) -> None:
    """Attach the three scores to one span on the propqa-eval dataset. Never raises into the eval."""
    client = get_langfuse_client()
    if client is None:
        print("Langfuse: skipped (no keys)")
        return
    try:
        _ensure_dataset(client)
        _score_run(client, report)
        flush = getattr(client, "flush", None)
        if flush is not None:
            flush()
        print("Langfuse: recorded propqa-eval")
    except Exception as exc:
        logger.warning("langfuse eval run was not recorded", extra={"extra_data": {"error": type(exc).__name__}})
        print(f"Langfuse: not recorded ({type(exc).__name__})")


def _ensure_dataset(client) -> None:
    create = getattr(client, "create_dataset", None)
    if create is None:
        return
    try:
        create(name=DATASET_NAME)
    except Exception:
        # The dataset already exists, or this client records the run without a prior create.
        return


def _score_run(client, report: dict) -> None:
    scores = {
        name: float(value)
        for name, value in report["metrics"].items()
        if isinstance(value, (int, float))
    }
    start = getattr(client, "start_as_current_observation", None) or getattr(client, "start_as_current_span", None)
    if start is None:
        return
    with start(name=DATASET_NAME) as span:
        update = getattr(span, "update", None)
        if update is not None:
            update(metadata={"split": report["split"], "metrics": scores, "dataset": DATASET_NAME})
        score = getattr(client, "score_current_span", None) or getattr(span, "score", None)
        if score is None:
            return
        for name, value in scores.items():
            score(name=name, value=value)
