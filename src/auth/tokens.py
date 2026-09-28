"""Signed access tokens and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import threading
from datetime import datetime, timedelta

import jwt

from auth.errors import InvalidToken, TokenExpired
from auth.models import UserRecord
from common.logger import get_logger
from common.services.app_clock import AppClock
from config import ENVIRONMENT, ActiveConfig

logger = get_logger("auth.tokens")

ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
MIN_SIGNING_KEY_BYTES = 32

_ephemeral_key: str | None = None
_key_lock = threading.Lock()


def signing_key() -> str:
    """The HS256 key. Deployed environments must configure a strong one.

    Local runs without a key get a random one per process, so tokens do not
    survive a restart.
    """
    global _ephemeral_key
    configured = ActiveConfig.JWT_SIGNING_KEY
    if configured:
        if ENVIRONMENT.is_deployed and len(configured.encode("utf-8")) < MIN_SIGNING_KEY_BYTES:
            raise RuntimeError(f"JWT_SIGNING_KEY must be at least {MIN_SIGNING_KEY_BYTES} bytes.")
        return configured
    if ENVIRONMENT.is_deployed:
        raise RuntimeError(f"JWT_SIGNING_KEY is required in {ENVIRONMENT.value}.")
    with _key_lock:
        if _ephemeral_key is None:
            logger.warning("JWT_SIGNING_KEY is not set; using a per-process key")
            _ephemeral_key = secrets.token_urlsafe(48)
        return _ephemeral_key


def issue_access_token(user: UserRecord, *, now: datetime | None = None) -> str:
    issued = now or AppClock.utcnow()
    claims = {
        "sub": user.id,
        "role": user.role.value,
        "typ": ACCESS_TOKEN_TYPE,
        "iss": ActiveConfig.JWT_ISSUER,
        "iat": issued,
        "exp": issued + timedelta(seconds=ActiveConfig.JWT_ACCESS_TOKEN_TTL_SECONDS),
    }
    return jwt.encode(claims, signing_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    """The user id the token was issued to. Raises TokenExpired or InvalidToken."""
    try:
        claims = jwt.decode(
            token,
            signing_key(),
            algorithms=[ALGORITHM],
            issuer=ActiveConfig.JWT_ISSUER,
            options={"require": ["sub", "exp", "iat", "iss", "typ"]},
        )
    except jwt.ExpiredSignatureError:
        raise TokenExpired() from None
    except jwt.PyJWTError:
        raise InvalidToken() from None
    if claims.get("typ") != ACCESS_TOKEN_TYPE or not isinstance(claims.get("sub"), str):
        raise InvalidToken()
    return claims["sub"]


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Only this digest is stored. The token has enough entropy that no salt is needed."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expiry(now: datetime | None = None) -> datetime:
    return (now or AppClock.utcnow()) + timedelta(days=ActiveConfig.JWT_REFRESH_TOKEN_TTL_DAYS)
