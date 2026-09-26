"""Request body for the streaming chat route."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent.sql.listing_details import MAX_FOCUSED_LISTINGS
from common.session import safe_thread_id, safe_user_id


class ChatRequest(BaseModel):
    """The chat UI sends ``session_id`` and ``user_id``. ``thread_id`` stays for callers that already use it.

    ``focused_property_ids`` are the listings the user picked on screen to ask about.
    """

    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=64)
    user_id: str | None = Field(default=None, max_length=80)
    session_profile: dict | None = None
    focused_property_ids: list[int] = Field(default_factory=list, max_length=MAX_FOCUSED_LISTINGS)

    @field_validator("message")
    @classmethod
    def message_has_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Message is empty.")
        return text

    @field_validator("thread_id", "session_id")
    @classmethod
    def thread_id_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = safe_thread_id(value)
        if text is None:
            raise ValueError("Thread id must be letters and numbers.")
        return text

    @field_validator("user_id")
    @classmethod
    def user_id_is_safe(cls, value: str | None) -> str | None:
        return safe_user_id(value)

    @field_validator("focused_property_ids")
    @classmethod
    def focused_ids_are_listings(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("Listing ids must be positive.")
        return list(dict.fromkeys(value))
