"""HTTP export and delete. Mount `router` on the API app."""

from __future__ import annotations

from fastapi import APIRouter

from agent.memory.views import user_memory as views

router = APIRouter()


@router.get("/users/{user_id}/memory")
def export_memory(user_id: str) -> list[dict]:
    return views.export_memory(user_id)


@router.delete("/users/{user_id}/memory")
def delete_memory(
    user_id: str,
    cluster: str | None = None,
    memory_id: str | None = None,
) -> dict:
    return views.delete_memory(user_id, cluster=cluster, memory_id=memory_id)
