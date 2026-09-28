"""Accounts and refresh tokens as the auth service sees them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    email: str
    name: str
    phone: str | None
    password_hash: str
    role: UserRole
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    """What sign-up, sign-in, and refresh hand back to the client."""

    user: UserRecord
    access_token: str
    refresh_token: str


def normalize_email(email: str) -> str:
    return email.strip().lower()
