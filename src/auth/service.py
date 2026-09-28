"""Sign-up, sign-in, token refresh, and sign-out."""

from __future__ import annotations

from auth.errors import InvalidCredentials, InvalidToken
from auth.models import AuthSession, UserRecord
from auth.passwords import hash_password, verify_password
from auth.storage import UserRepository
from auth.tokens import (
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    refresh_token_expiry,
)
from common.services.app_clock import AppClock


def register(
    repository: UserRepository, *, email: str, name: str, password: str, phone: str | None
) -> AuthSession:
    now = AppClock.utcnow()
    user = repository.create_user(
        email=email, name=name, phone=phone, password_hash=hash_password(password), now=now
    )
    return _start_session(repository, user)


def sign_in(repository: UserRepository, *, email: str, password: str) -> AuthSession:
    user = repository.get_user_by_email(email)
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise InvalidCredentials()
    return _start_session(repository, user)


def refresh(repository: UserRepository, refresh_token: str) -> AuthSession:
    """Swap a refresh token for a new pair. The old token stops working."""
    now = AppClock.utcnow()
    successor = new_refresh_token()
    user_id = repository.rotate_refresh_token(
        hash_refresh_token(refresh_token),
        hash_refresh_token(successor),
        expires_at=refresh_token_expiry(now),
        now=now,
    )
    user = repository.get_user(user_id) if user_id else None
    if user is None:
        raise InvalidToken()
    return AuthSession(user=user, access_token=issue_access_token(user, now=now), refresh_token=successor)


def sign_out(repository: UserRepository, refresh_token: str) -> None:
    repository.revoke_refresh_token(hash_refresh_token(refresh_token), now=AppClock.utcnow())


def current_user(repository: UserRepository, user_id: str) -> UserRecord:
    user = repository.get_user(user_id)
    if user is None:
        raise InvalidToken()
    return user


def _start_session(repository: UserRepository, user: UserRecord) -> AuthSession:
    now = AppClock.utcnow()
    token = new_refresh_token()
    repository.add_refresh_token(
        user.id, hash_refresh_token(token), expires_at=refresh_token_expiry(now), now=now
    )
    return AuthSession(user=user, access_token=issue_access_token(user, now=now), refresh_token=token)
