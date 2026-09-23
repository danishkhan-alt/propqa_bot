"""HTTP handlers for user memory export and delete."""

from __future__ import annotations

from fastapi import HTTPException

from agent.memory.maintenance.privacy import delete_user_memory, export_user_memory
from agent.memory.models.types import ALL_CLUSTERS
from agent.memory.session.bootstrap import get_repository


def require_repository():
    repository = get_repository()
    if repository is None:
        raise HTTPException(status_code=503, detail="memory store is not configured")
    return repository


def export_memory(user_id: str) -> list[dict]:
    return export_user_memory(require_repository(), user_id)


def delete_memory(
    user_id: str,
    cluster: str | None = None,
    memory_id: str | None = None,
) -> dict:
    if not cluster and not memory_id:
        raise HTTPException(status_code=400, detail="cluster or memory_id is required")
    if cluster and cluster not in ALL_CLUSTERS:
        raise HTTPException(status_code=400, detail="unknown cluster")
    count = delete_user_memory(
        require_repository(), user_id, cluster=cluster, memory_id=memory_id
    )
    return {"status": "deleted", "count": count}
