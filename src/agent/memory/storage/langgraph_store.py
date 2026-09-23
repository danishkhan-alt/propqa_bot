"""PropQAMemoryStore: LangGraph BaseStore over user_memories."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from langgraph.store.base import (
    BaseStore,
    GetOp,
    InvalidNamespaceError,
    Item,
    ListNamespacesOp,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

from agent.memory.storage.repository import InMemoryRepository
from agent.memory.models.types import MemoryRecord, public_record, utcnow


class PropQAMemoryStore(BaseStore):
    """`store.put` / `store.search` for graph nodes. Consolidation uses the repository."""

    supports_ttl = True

    def __init__(
        self,
        repository: InMemoryRepository,
        *,
        embed=None,
        dims: int = 1024,
    ) -> None:
        self.repository = repository
        self._embed = embed
        self.dims = dims

    def batch(self, ops: Iterable) -> list[Result]:
        return [self._run(op) for op in ops]

    async def abatch(self, ops: Iterable) -> list[Result]:
        return await asyncio.to_thread(self.batch, list(ops))

    def _run(self, op) -> Result:
        if isinstance(op, GetOp):
            return self._get(op)
        if isinstance(op, SearchOp):
            return self._search(op)
        if isinstance(op, PutOp):
            self._put(op)
            return None
        if isinstance(op, ListNamespacesOp):
            return self._namespaces(op)
        raise TypeError(f"unsupported store operation: {type(op).__name__}")

    def _user_id(self, namespace: tuple[str, ...]) -> str:
        if len(namespace) < 2 or namespace[0] != "users" or not str(namespace[1]).strip():
            raise InvalidNamespaceError("memory namespace must be ('users', user_id)")
        return str(namespace[1])

    def _get(self, op: GetOp) -> Item | None:
        user_id = self._user_id(tuple(op.namespace))
        record = self.repository.get(user_id, str(op.key))
        if record is None:
            return None
        return _item(record)

    def _search(self, op: SearchOp) -> list[SearchItem]:
        user_id = self._user_id(tuple(op.namespace_prefix))
        status, clusters = _filter(op.filter)
        embedding = None
        if op.query and self._embed is not None:
            embedding = list(self._embed([op.query])[0])
            if len(embedding) != self.dims:
                raise ValueError(f"query embedding must have {self.dims} dimensions")
        hits = self.repository.search(
            user_id,
            query=op.query,
            embedding=embedding,
            status=status,
            clusters=clusters,
            limit=op.limit,
            offset=op.offset,
        )
        return [_search_item(record, score) for record, score in hits]

    def _put(self, op: PutOp) -> None:
        user_id = self._user_id(tuple(op.namespace))
        if op.value is None:
            record = self.repository.get(user_id, str(op.key))
            if record is None:
                return
            record.status = "deleted"
            record.embedding = None
            record.updated_at = utcnow()
            self.repository.update(record)
            self.repository.add_event(user_id, record.id, "deleted_by_user", "user")
            return
        now = utcnow()
        expires = None
        if op.ttl:
            expires = now + timedelta(minutes=float(op.ttl))
        value = dict(op.value)
        embedding = None
        if op.index is not False and self._embed is not None and value.get("content"):
            embedding = list(self._embed([str(value["content"])])[0])
            if len(embedding) != self.dims:
                raise ValueError(f"embedding must have {self.dims} dimensions")
        existing = self.repository.get(user_id, str(op.key))
        record = MemoryRecord(
            id=existing.id if existing else str(op.key),
            user_id=user_id,
            type=str(value.get("type") or "preference"),
            cluster=str(value.get("cluster") or "property_prefs"),
            slot=value.get("slot"),
            content=str(value.get("content") or ""),
            structured=value.get("structured"),
            embedding=embedding if embedding is not None else (existing.embedding if existing else None),
            confidence=float(value.get("confidence") if value.get("confidence") is not None else 0.8),
            importance=float(value.get("importance") if value.get("importance") is not None else 0.5),
            provenance=str(value.get("provenance") or "explicit"),
            source_thread_id=value.get("source_thread_id"),
            source_message_id=value.get("source_message_id"),
            status=str(value.get("status") or "active"),
            supersedes_id=value.get("supersedes_id") or (existing.supersedes_id if existing else None),
            valid_from=existing.valid_from if existing else now,
            expires_at=expires if expires is not None else (existing.expires_at if existing else None),
            last_accessed_at=existing.last_accessed_at if existing else None,
            access_count=existing.access_count if existing else 0,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        if existing:
            record.id = existing.id
            self.repository.update(record)
            self.repository.add_event(user_id, record.id, "updated", "extractor")
        else:
            self._retire_slot(record)
            self.repository.insert(record)
            self.repository.add_event(user_id, record.id, "created", "extractor")

    def _retire_slot(self, record: MemoryRecord) -> None:
        if not record.slot or record.status != "active":
            return
        current = self.repository.get_active_slot(record.user_id, record.slot)
        if current is None or current.id == record.id:
            return
        current.status = "superseded"
        current.updated_at = record.updated_at
        self.repository.update(current)
        record.supersedes_id = current.id
        self.repository.add_event(
            record.user_id,
            current.id,
            "superseded",
            "extractor",
            {"memory_id": record.id},
        )

    def _namespaces(self, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        namespaces = [("users", user_id) for user_id in self.repository.list_user_ids()]
        for condition in op.match_conditions:
            path = tuple(condition.path)
            if condition.match_type == "prefix":
                namespaces = [item for item in namespaces if item[: len(path)] == path]
            elif condition.match_type == "suffix":
                namespaces = [item for item in namespaces if item[-len(path) :] == path]
        if op.max_depth is not None:
            trimmed = [item[: op.max_depth] for item in namespaces]
            namespaces = list(dict.fromkeys(trimmed))
        return namespaces[op.offset : op.offset + op.limit]


def _filter(raw: dict[str, Any] | None) -> tuple[str | None, list[str] | None]:
    if not raw:
        return "active", None
    status = raw.get("status")
    cluster = raw.get("cluster")
    clusters = None
    if isinstance(cluster, str):
        clusters = [cluster]
    elif isinstance(cluster, (list, tuple, set)):
        clusters = [str(item) for item in cluster]
    return (str(status) if status is not None else None), clusters


def _item(record: MemoryRecord) -> Item:
    return Item(
        value=public_record(record),
        key=record.id,
        namespace=("users", record.user_id),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _search_item(record: MemoryRecord, score: float) -> SearchItem:
    value = public_record(record, similarity=score)
    return SearchItem(
        ("users", record.user_id),
        record.id,
        value,
        record.created_at,
        record.updated_at,
        score,
    )
