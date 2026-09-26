"""Postgres + pgvector backing for user_memories.

The memory cache stays in Redis. This table is the durable copy.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from agent.memory.models.column_map import (
    DEFAULT_COLUMN_SPECS,
    ColumnSpec,
    parse_cluster,
    parse_slot,
)
from agent.memory.models.records import MemoryRecord, MemorySettings, utcnow
from agent.memory.storage.in_memory_repository import new_memory_id, token_similarity

_transaction_connection: contextvars.ContextVar = contextvars.ContextVar("memory_pg_conn", default=None)

DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
    CREATE TYPE memory_type AS ENUM ('profile','preference','semantic','episodic','goal','ephemeral');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE memory_provenance AS ENUM ('explicit','inferred','system','summarized');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE memory_status AS ENUM ('active','superseded','expired','deleted','contradicted');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS user_memories (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           text NOT NULL,
    type              memory_type NOT NULL,
    cluster           text NOT NULL,
    slot              text,
    content           text NOT NULL,
    structured        jsonb,
    embedding         vector(1024),
    confidence        real NOT NULL,
    importance        real NOT NULL,
    provenance        memory_provenance NOT NULL,
    source_thread_id  text,
    source_message_id text,
    status            memory_status NOT NULL DEFAULT 'active',
    supersedes_id     uuid REFERENCES user_memories(id),
    valid_from        timestamptz NOT NULL DEFAULT now(),
    expires_at        timestamptz,
    last_accessed_at  timestamptz,
    access_count      int NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_memories_user_status_cluster_idx
    ON user_memories (user_id, status, cluster);
CREATE INDEX IF NOT EXISTS user_memories_user_slot_idx
    ON user_memories (user_id, slot) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS user_memories_active_slot_idx
    ON user_memories (user_id, slot) WHERE status = 'active' AND slot IS NOT NULL;
CREATE INDEX IF NOT EXISTS user_memories_embedding_idx
    ON user_memories USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS user_profile_summary (
    user_id     text PRIMARY KEY,
    summary     text NOT NULL,
    structured  jsonb NOT NULL,
    version     int NOT NULL DEFAULT 1,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memory_events (
    id          bigserial PRIMARY KEY,
    user_id     text NOT NULL,
    memory_id   uuid,
    event       text NOT NULL,
    actor       text NOT NULL,
    detail      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_memory_settings (
    user_id          text PRIMARY KEY,
    memory_enabled   bool NOT NULL DEFAULT true,
    allowed_clusters text[] NOT NULL DEFAULT '{property_prefs,budget,location,persona,goal}',
    retention_days   int
);

CREATE TABLE IF NOT EXISTS memory_column_map (
    logical_col  text PRIMARY KEY,
    physical_col text NOT NULL,
    domain       text NOT NULL,
    value_type   text NOT NULL,
    filter_key   text,
    slot         text,
    cluster      text,
    exclusive    bool NOT NULL DEFAULT false
);
"""

COLUMN_MAP_UPGRADE = """
ALTER TABLE memory_column_map ADD COLUMN IF NOT EXISTS filter_key text;
ALTER TABLE memory_column_map ADD COLUMN IF NOT EXISTS slot text;
ALTER TABLE memory_column_map ADD COLUMN IF NOT EXISTS cluster text;
ALTER TABLE memory_column_map ADD COLUMN IF NOT EXISTS exclusive bool NOT NULL DEFAULT false;
"""


class PostgresMemoryRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(DDL)
            conn.execute(COLUMN_MAP_UPGRADE)
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO memory_column_map (
                        logical_col, physical_col, domain, value_type,
                        filter_key, slot, cluster, exclusive
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (logical_col) DO UPDATE SET
                        filter_key = EXCLUDED.filter_key,
                        slot = EXCLUDED.slot,
                        cluster = EXCLUDED.cluster,
                        exclusive = EXCLUDED.exclusive
                    """,
                    [
                        (
                            spec.logical_col,
                            spec.physical_col,
                            spec.domain,
                            spec.value_type,
                            spec.filter_key,
                            spec.slot.value if spec.slot else None,
                            spec.cluster.value if spec.cluster else None,
                            spec.exclusive,
                        )
                        for spec in DEFAULT_COLUMN_SPECS
                    ],
                )
            conn.commit()

    @contextmanager
    def transaction(self):
        if _transaction_connection.get() is not None:
            yield
            return
        with self._pool.connection() as conn:
            with conn.transaction():
                token = _transaction_connection.set(conn)
                try:
                    yield
                finally:
                    _transaction_connection.reset(token)

    def get_column_specs(self) -> dict[str, ColumnSpec]:
        rows = self._fetch(
            """
            SELECT logical_col, physical_col, domain, value_type,
                   filter_key, slot, cluster, exclusive
            FROM memory_column_map
            """
        )
        return {
            row["logical_col"]: ColumnSpec(
                logical_col=row["logical_col"],
                physical_col=row["physical_col"],
                domain=row["domain"],
                value_type=row["value_type"],
                filter_key=row.get("filter_key"),
                slot=parse_slot(row.get("slot")),
                cluster=parse_cluster(row.get("cluster")),
                exclusive=bool(row.get("exclusive")),
            )
            for row in rows
        }

    def rename_column(self, logical: str, physical: str) -> None:
        self._execute(
            "UPDATE memory_column_map SET physical_col = %s WHERE logical_col = %s",
            (physical, logical),
        )

    def get(self, user_id: str, memory_id: str) -> MemoryRecord | None:
        rows = self._fetch(
            "SELECT * FROM user_memories WHERE user_id = %s AND id = %s",
            (user_id, memory_id),
        )
        return _row_to_record(rows[0]) if rows else None

    def get_active_slot(self, user_id: str, slot: str) -> MemoryRecord | None:
        rows = self._fetch(
            """
            SELECT * FROM user_memories
            WHERE user_id = %s AND slot = %s AND status = 'active'
            LIMIT 1
            """,
            (user_id, slot),
        )
        return _row_to_record(rows[0]) if rows else None

    def insert(self, record: MemoryRecord) -> MemoryRecord:
        self._execute(
            """
            INSERT INTO user_memories (
                id, user_id, type, cluster, slot, content, structured, embedding,
                confidence, importance, provenance, source_thread_id, source_message_id,
                status, supersedes_id, valid_from, expires_at, last_accessed_at,
                access_count, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s::vector,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s
            )
            """,
            _record_params(record),
        )
        return record

    def update(self, record: MemoryRecord) -> None:
        self._execute(
            """
            UPDATE user_memories SET
                type = %s, cluster = %s, slot = %s, content = %s, structured = %s,
                embedding = %s::vector, confidence = %s, importance = %s, provenance = %s,
                status = %s, supersedes_id = %s, expires_at = %s, last_accessed_at = %s,
                access_count = %s, updated_at = %s
            WHERE id = %s AND user_id = %s
            """,
            (
                record.type,
                record.cluster,
                record.slot,
                record.content,
                _json(record.structured),
                _to_pgvector_literal(record.embedding),
                record.confidence,
                record.importance,
                record.provenance,
                record.status,
                record.supersedes_id,
                record.expires_at,
                record.last_accessed_at,
                record.access_count,
                record.updated_at,
                record.id,
                record.user_id,
            ),
        )

    def search(
        self,
        user_id: str,
        *,
        query: str | None = None,
        embedding: list[float] | None = None,
        status: str | None = "active",
        clusters: list[str] | None = None,
        limit: int = 10,
        offset: int = 0,
        now: datetime | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        moment = now or utcnow()
        if clusters is not None and not clusters:
            return []
        where = ["user_id = %s"]
        params: list[Any] = [user_id]
        if status is not None:
            where.append("status = %s")
            params.append(status)
        if clusters is not None:
            where.append("cluster = ANY(%s)")
            params.append(clusters)
        if status == "active":
            where.append("(expires_at IS NULL OR expires_at > %s)")
            params.append(moment)
        clause = " AND ".join(where)
        if embedding:
            vector = _to_pgvector_literal(embedding)
            rows = self._fetch(
                f"""
                SELECT *, 1 - (embedding <=> %s::vector) AS similarity
                FROM user_memories
                WHERE {clause} AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s OFFSET %s
                """,
                [vector, *params, vector, limit, offset],
            )
            return [(_row_to_record(row), float(row["similarity"])) for row in rows]
        rows = self._fetch(
            f"SELECT * FROM user_memories WHERE {clause} ORDER BY updated_at DESC LIMIT %s",
            [*params, max(limit * 5, 50)],
        )
        scored = []
        for row in rows:
            record = _row_to_record(row)
            score = token_similarity(query, record.content) if query else 0.0
            scored.append((record, score))
        scored.sort(key=lambda pair: (pair[1], pair[0].updated_at), reverse=True)
        return scored[offset : offset + limit]

    def list_active(self, user_id: str, *, now: datetime | None = None) -> list[MemoryRecord]:
        moment = now or utcnow()
        rows = self._fetch(
            """
            SELECT * FROM user_memories
            WHERE user_id = %s AND status = 'active'
              AND (expires_at IS NULL OR expires_at > %s)
            """,
            (user_id, moment),
        )
        return [_row_to_record(row) for row in rows]

    def list_all(self, user_id: str) -> list[MemoryRecord]:
        rows = self._fetch("SELECT * FROM user_memories WHERE user_id = %s", (user_id,))
        return [_row_to_record(row) for row in rows]

    def list_user_ids(self) -> list[str]:
        rows = self._fetch("SELECT DISTINCT user_id FROM user_memories ORDER BY user_id")
        return [row["user_id"] for row in rows]

    def record_access(self, memory_ids: list[str], *, now: datetime | None = None) -> None:
        if not memory_ids:
            return
        self._execute(
            """
            UPDATE user_memories
            SET last_accessed_at = %s, access_count = access_count + 1
            WHERE id = ANY(%s)
            """,
            (now or utcnow(), memory_ids),
        )

    def hard_delete_by_status(self, *, status: str, older_than: datetime) -> int:
        return self._execute(
            "DELETE FROM user_memories WHERE status = %s AND updated_at < %s",
            (status, older_than),
        )

    def add_event(
        self,
        user_id: str,
        memory_id: str | None,
        event: str,
        actor: str,
        detail: dict | None = None,
        now: datetime | None = None,
    ) -> dict:
        rows = self._fetch(
            """
            INSERT INTO memory_events (user_id, memory_id, event, actor, detail, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, memory_id, event, actor, detail, created_at
            """,
            (user_id, memory_id, event, actor, _json(detail or {}), now or utcnow()),
        )
        row = rows[0]
        row["memory_id"] = str(row["memory_id"]) if row["memory_id"] else None
        return row

    def count_events(self, user_id: str, event: str) -> int:
        rows = self._fetch(
            "SELECT count(*) AS n FROM memory_events WHERE user_id = %s AND event = %s",
            (user_id, event),
        )
        return int(rows[0]["n"])

    def was_decayed_since(self, memory_id: str, *, since: datetime) -> bool:
        rows = self._fetch(
            """
            SELECT 1 FROM memory_events
            WHERE memory_id = %s AND created_at >= %s AND detail @> %s
            LIMIT 1
            """,
            (memory_id, since, _json({"decay": True})),
        )
        return bool(rows)

    def latest_open_contradiction(self, user_id: str) -> dict | None:
        rows = self._fetch(
            """
            SELECT * FROM memory_events
            WHERE user_id = %s AND event = 'contradiction_flagged'
              AND COALESCE(detail->>'asked', 'false') <> 'true'
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        )
        if not rows:
            return None
        row = rows[0]
        row["memory_id"] = str(row["memory_id"]) if row["memory_id"] else None
        return row

    def merge_event_detail(self, event_id: int, **detail: Any) -> None:
        self._execute(
            "UPDATE memory_events SET detail = COALESCE(detail, '{}'::jsonb) || %s WHERE id = %s",
            (_json(detail), event_id),
        )

    def get_settings(self, user_id: str) -> MemorySettings:
        rows = self._fetch("SELECT * FROM user_memory_settings WHERE user_id = %s", (user_id,))
        if not rows:
            return MemorySettings(user_id=user_id)
        row = rows[0]
        return MemorySettings(
            user_id=user_id,
            memory_enabled=bool(row["memory_enabled"]),
            allowed_clusters=tuple(row["allowed_clusters"] or ()),
            retention_days=row["retention_days"],
        )

    def save_settings(self, settings: MemorySettings) -> None:
        self._execute(
            """
            INSERT INTO user_memory_settings (user_id, memory_enabled, allowed_clusters, retention_days)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                memory_enabled = EXCLUDED.memory_enabled,
                allowed_clusters = EXCLUDED.allowed_clusters,
                retention_days = EXCLUDED.retention_days
            """,
            (
                settings.user_id,
                settings.memory_enabled,
                list(settings.allowed_clusters),
                settings.retention_days,
            ),
        )

    def get_profile(self, user_id: str) -> dict | None:
        rows = self._fetch("SELECT * FROM user_profile_summary WHERE user_id = %s", (user_id,))
        if not rows:
            return None
        row = rows[0]
        return {
            "user_id": user_id,
            "summary": row["summary"],
            "structured": row["structured"] or {},
            "version": row["version"],
            "updated_at": row["updated_at"],
        }

    def save_profile(self, user_id: str, summary: str, structured: dict, *, now: datetime | None = None) -> None:
        self._execute(
            """
            INSERT INTO user_profile_summary (user_id, summary, structured, version, updated_at)
            VALUES (%s, %s, %s, 1, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                structured = EXCLUDED.structured,
                version = user_profile_summary.version + 1,
                updated_at = EXCLUDED.updated_at
            """,
            (user_id, summary, _json(structured), now or utcnow()),
        )

    def _fetch(self, sql: str, params: tuple | list = ()) -> list[dict]:
        conn = _transaction_connection.get()
        if conn is None:
            with self._pool.connection() as owned:
                with owned.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall() if cur.description else []
                owned.commit()
                return list(rows)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall()) if cur.description else []

    def _execute(self, sql: str, params: tuple | list = ()) -> int:
        conn = _transaction_connection.get()
        if conn is None:
            with self._pool.connection() as owned:
                with owned.cursor() as cur:
                    cur.execute(sql, params)
                    count = cur.rowcount
                owned.commit()
                return count
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def _json(value: Any):
    if value is None:
        return None
    return Jsonb(value)


def _to_pgvector_literal(values: list[float] | None) -> str | None:
    if not values:
        return None
    return "[" + ",".join(f"{float(item):.8f}" for item in values) + "]"


def _parse_vector(value) -> list[float] | None:
    if value is None or isinstance(value, list):
        return value
    text = str(value).strip("[]")
    if not text:
        return None
    return [float(part) for part in text.split(",")]


def _row_to_record(row: dict) -> MemoryRecord:
    return MemoryRecord(
        id=str(row["id"]),
        user_id=row["user_id"],
        type=row["type"],
        cluster=row["cluster"],
        slot=row["slot"],
        content=row["content"],
        structured=row["structured"],
        embedding=_parse_vector(row["embedding"]),
        confidence=float(row["confidence"]),
        importance=float(row["importance"]),
        provenance=row["provenance"],
        source_thread_id=row["source_thread_id"],
        source_message_id=row["source_message_id"],
        status=row["status"],
        supersedes_id=str(row["supersedes_id"]) if row["supersedes_id"] else None,
        valid_from=row["valid_from"],
        expires_at=row["expires_at"],
        last_accessed_at=row["last_accessed_at"],
        access_count=int(row["access_count"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _record_params(record: MemoryRecord) -> tuple:
    return (
        record.id or new_memory_id(),
        record.user_id,
        record.type,
        record.cluster,
        record.slot,
        record.content,
        _json(record.structured),
        _to_pgvector_literal(record.embedding),
        record.confidence,
        record.importance,
        record.provenance,
        record.source_thread_id,
        record.source_message_id,
        record.status,
        record.supersedes_id,
        record.valid_from,
        record.expires_at,
        record.last_accessed_at,
        record.access_count,
        record.created_at,
        record.updated_at,
    )

