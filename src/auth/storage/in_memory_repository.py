"""In-process accounts and refresh tokens. Postgres implements the same methods."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime

from auth.errors import EmailTaken
from auth.models import UserRecord, UserRole, normalize_email


@dataclass(slots=True)
class _RefreshToken:
    user_id: str
    expires_at: datetime
    revoked_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}
        self._tokens: dict[str, _RefreshToken] = {}
        self._lock = threading.RLock()

    def ensure_schema(self) -> None:
        return None

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
        email = normalize_email(email)
        with self._lock:
            if any(user.email == email for user in self._users.values()):
                raise EmailTaken()
            user = UserRecord(
                id=str(uuid.uuid4()),
                email=email,
                name=name,
                phone=phone,
                password_hash=password_hash,
                role=role,
                created_at=now,
                updated_at=now,
            )
            self._users[user.id] = user
            return user

    def get_user(self, user_id: str) -> UserRecord | None:
        with self._lock:
            return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> UserRecord | None:
        email = normalize_email(email)
        with self._lock:
            return next((user for user in self._users.values() if user.email == email), None)

    def add_refresh_token(self, user_id: str, token_hash: str, *, expires_at: datetime, now: datetime) -> None:
        with self._lock:
            self._purge(user_id, now)
            self._tokens[token_hash] = _RefreshToken(user_id=user_id, expires_at=expires_at)

    def rotate_refresh_token(
        self, token_hash: str, new_token_hash: str, *, expires_at: datetime, now: datetime
    ) -> str | None:
        with self._lock:
            current = self._tokens.get(token_hash)
            if current is None or not current.is_active(now):
                return None
            current.revoked_at = now
            self._tokens[new_token_hash] = _RefreshToken(user_id=current.user_id, expires_at=expires_at)
            return current.user_id

    def revoke_refresh_token(self, token_hash: str, *, now: datetime) -> bool:
        with self._lock:
            current = self._tokens.get(token_hash)
            if current is None or current.revoked_at is not None:
                return False
            current.revoked_at = now
            return True

    def _purge(self, user_id: str, now: datetime) -> None:
        stale = [
            key
            for key, token in self._tokens.items()
            if token.user_id == user_id and not token.is_active(now)
        ]
        for key in stale:
            del self._tokens[key]
