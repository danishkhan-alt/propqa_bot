"""Accounts and refresh tokens in the chatbot database (never the warehouse)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from psycopg import errors as pg_errors

from auth.errors import EmailTaken
from auth.models import UserRecord, UserRole, normalize_email
from common.utils.uuid_validation import is_valid_uuid

DDL = """
CREATE TABLE IF NOT EXISTS chatbot_users (
    id             uuid PRIMARY KEY,
    email          text NOT NULL,
    name           text NOT NULL,
    phone          text,
    password_hash  text NOT NULL,
    role           text NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS chatbot_users_email_idx
    ON chatbot_users (lower(email));

CREATE TABLE IF NOT EXISTS chatbot_refresh_tokens (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES chatbot_users(id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chatbot_refresh_tokens_user_idx
    ON chatbot_refresh_tokens (user_id);
"""

_USER_COLUMNS = "id, email, name, phone, password_hash, role, created_at, updated_at"


class PostgresUserRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(DDL)
            conn.commit()

    def create_user(
        self,
        *,
        email: str,
        name: str,
        phone: str | None,
        password_hash: str,
        now: datetime,
        role: UserRole = UserRole.USER,
    ) -> UserRecord:
        try:
            rows = self._fetch(
                f"""
                INSERT INTO chatbot_users (id, email, name, phone, password_hash, role, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_USER_COLUMNS}
                """,
                (uuid.uuid4(), normalize_email(email), name, phone, password_hash, role.value, now, now),
            )
        except pg_errors.UniqueViolation:
            raise EmailTaken() from None
        return _row_to_user(rows[0])

    def get_user(self, user_id: str) -> UserRecord | None:
        if not is_valid_uuid(user_id):
            return None
        rows = self._fetch(f"SELECT {_USER_COLUMNS} FROM chatbot_users WHERE id = %s", (user_id,))
        return _row_to_user(rows[0]) if rows else None

    def get_user_by_email(self, email: str) -> UserRecord | None:
        rows = self._fetch(
            f"SELECT {_USER_COLUMNS} FROM chatbot_users WHERE lower(email) = %s",
            (normalize_email(email),),
        )
        return _row_to_user(rows[0]) if rows else None

    def add_refresh_token(self, user_id: str, token_hash: str, *, expires_at: datetime, now: datetime) -> None:
        with self._pool.connection() as conn, conn.transaction():
            _purge_stale_tokens(conn, user_id, now)
            _insert_token(conn, user_id, token_hash, expires_at, now)

    def rotate_refresh_token(
        self, token_hash: str, new_token_hash: str, *, expires_at: datetime, now: datetime
    ) -> str | None:
        """Revoke an active token and issue its successor in one step.

        The guarded UPDATE lets exactly one of two concurrent rotations win.
        """
        with self._pool.connection() as conn, conn.transaction():
            row = conn.execute(
                """
                UPDATE chatbot_refresh_tokens SET revoked_at = %s
                WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > %s
                RETURNING user_id
                """,
                (now, token_hash, now),
            ).fetchone()
            if row is None:
                return None
            user_id = str(row["user_id"])
            _insert_token(conn, user_id, new_token_hash, expires_at, now)
            return user_id

    def revoke_refresh_token(self, token_hash: str, *, now: datetime) -> bool:
        with self._pool.connection() as conn:
            cursor = conn.execute(
                "UPDATE chatbot_refresh_tokens SET revoked_at = %s WHERE token_hash = %s AND revoked_at IS NULL",
                (now, token_hash),
            )
            conn.commit()
            return cursor.rowcount > 0

    def _fetch(self, sql: str, params: Any = None) -> list[dict]:
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            conn.commit()
            return rows


def _insert_token(conn, user_id: str, token_hash: str, expires_at: datetime, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO chatbot_refresh_tokens (id, user_id, token_hash, expires_at, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (uuid.uuid4(), user_id, token_hash, expires_at, now),
    )


def _purge_stale_tokens(conn, user_id: str, now: datetime) -> None:
    conn.execute(
        """
        DELETE FROM chatbot_refresh_tokens
        WHERE user_id = %s AND (expires_at <= %s OR revoked_at IS NOT NULL)
        """,
        (user_id, now),
    )


def _row_to_user(row: dict) -> UserRecord:
    return UserRecord(
        id=str(row["id"]),
        email=row["email"],
        name=row["name"],
        phone=row["phone"],
        password_hash=row["password_hash"],
        role=UserRole(row["role"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
