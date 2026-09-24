"""Ids the chat UI is allowed to send."""

from __future__ import annotations

from common.utils.helpers import is_valid_uuid

_THREAD_MAX = 64
_USER_MAX = 80


def safe_thread_id(value: str | None) -> str | None:
    """A thread id is a uuid or letters and numbers, at most 64 characters."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > _THREAD_MAX:
        return None
    if is_valid_uuid(text) or text.isalnum():
        return text
    return None


def safe_user_id(value: str | None) -> str | None:
    """A user id is a uuid, letters and numbers, or ``anon-<uuid>``."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > _USER_MAX:
        return None
    if text.startswith("anon-") and is_valid_uuid(text.removeprefix("anon-")):
        return text
    if is_valid_uuid(text) or text.isalnum():
        return text
    return None
