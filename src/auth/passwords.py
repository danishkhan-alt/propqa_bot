"""bcrypt password hashes."""

from __future__ import annotations

import functools

import bcrypt

BCRYPT_ROUNDS = 12
# bcrypt reads at most 72 bytes; longer input is refused rather than silently cut.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    encoded = password.encode("utf-8")
    if password_hash is None or len(encoded) > MAX_PASSWORD_BYTES:
        bcrypt.checkpw(b"x", _dummy_hash())
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        return False


def _encode(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return encoded


@functools.cache
def _dummy_hash() -> bytes:
    """Checked when there is no real hash, so a miss costs as long as a wrong password."""
    return bcrypt.hashpw(b"propqa-timing-equaliser", bcrypt.gensalt(BCRYPT_ROUNDS))
