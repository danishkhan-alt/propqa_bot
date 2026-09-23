"""Consume `memq` off the request path. Explicit extraction runs before inference."""

from __future__ import annotations

import sys

from agent.memory.write.upsert import write_memories
from agent.memory.maintenance.consolidate import consolidate_user
from agent.memory.write.extract import extract_turn
from agent.memory.models.types import utcnow
from common.logger import get_logger

logger = get_logger("agent.memory")


def process_job(job: dict, repository, *, now=None, extract=None) -> list[str]:
    user_id = str(job.get("user_id") or "").strip()
    if not user_id:
        return []
    moment = now or utcnow()
    settings = repository.get_settings(user_id)
    if not settings.memory_enabled:
        return []
    ops = (extract or extract_turn)(job)
    allowed = set(settings.allowed_clusters)
    kept = [op for op in ops if op.op == "delete" or op.cluster in allowed]
    touched = write_memories(repository, user_id, kept, now=moment, actor="extractor")
    repository.add_event(user_id, None, "extracted", "worker", {"kept": len(kept)}, moment)
    if repository.count_events(user_id, "extracted") % 20 == 0:
        consolidate_user(repository, user_id, now=moment)
    return touched


def drain(hot, repository, *, limit: int = 50) -> int:
    done = 0
    for entry_id, job in hot.read(count=limit, block_ms=0):
        try:
            process_job(job, repository)
        except Exception:
            logger.exception("memory job failed")
            continue
        hot.ack(entry_id)
        done += 1
    return done


def run_forever(hot, repository) -> None:
    while True:
        jobs = hot.read(count=10, block_ms=2000)
        if not jobs:
            continue
        for entry_id, job in jobs:
            try:
                process_job(job, repository)
            except Exception:
                logger.exception("memory job failed")
                continue
            hot.ack(entry_id)


def main(argv: list[str] | None = None) -> None:
    from agent.memory.maintenance.consolidate import consolidate_all
    from agent.memory.session.bootstrap import open_hot, open_long_term_store

    args = list(sys.argv[1:] if argv is None else argv)
    store = open_long_term_store()
    if "--consolidate" in args:
        consolidate_all(store.repository)
        return
    run_forever(open_hot(), store.repository)


if __name__ == "__main__":
    main()
