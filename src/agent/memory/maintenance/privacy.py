"""Delete, export, and the memory kill switch."""

from __future__ import annotations

from agent.memory.models.records import utcnow
from agent.memory.session.working_memory import invalidate_user_memory_cache


def soft_delete_memories(
    repository,
    user_id: str,
    *,
    cluster: str | None = None,
    memory_id: str | None = None,
    all_clusters: bool = False,
    actor: str = "user",
) -> int:
    if memory_id:
        found = repository.get(user_id, memory_id)
        rows = [found] if found is not None and found.status == "active" else []
    elif cluster:
        rows = [row for row in repository.list_active(user_id) if row.cluster == cluster]
    elif all_clusters:
        rows = repository.list_active(user_id)
    else:
        return 0
    now = utcnow()
    with repository.transaction():
        for row in rows:
            row.status = "deleted"
            row.embedding = None
            row.updated_at = now
            repository.update(row)
            repository.add_event(
                user_id,
                row.id,
                "deleted_by_user",
                actor,
                {"cluster": cluster, "memory_id": memory_id},
                now,
            )
    if rows:
        invalidate_user_memory_cache(user_id)
    return len(rows)


def delete_user_memory(
    repository,
    user_id: str,
    *,
    cluster: str | None = None,
    memory_id: str | None = None,
) -> int:
    return soft_delete_memories(
        repository,
        user_id,
        cluster=cluster,
        memory_id=memory_id,
        actor="user",
    )


def export_user_memory(repository, user_id: str) -> list[dict]:
    """Active memories the user can read. No embeddings and no warehouse ids."""
    exported = []
    for row in repository.list_active(user_id):
        exported.append(
            {
                "id": row.id,
                "content": row.content,
                "provenance": row.provenance,
                "confidence": row.confidence,
                "created_at": row.created_at.isoformat(),
                "type": row.type,
                "cluster": row.cluster,
            }
        )
    return exported


def set_memory_enabled(repository, user_id: str, enabled: bool):
    settings = repository.get_settings(user_id)
    settings.memory_enabled = enabled
    repository.save_settings(settings)
    invalidate_user_memory_cache(user_id)
    return settings
