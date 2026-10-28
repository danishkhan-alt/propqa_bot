"""Body the chat UI already posts for a thumbs vote."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.session import safe_thread_id


class ThumbsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thumbs: Literal["up", "down"]
    message_id: str | None = Field(default=None, max_length=80)
    session_id: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)
    turn_id: str | None = Field(default=None, max_length=80)
    user_message: str | None = Field(default=None, max_length=20000)
    assistant_message: str | None = Field(default=None, max_length=20000)

    @field_validator("session_id")
    @classmethod
    def session_id_is_safe(cls, value: str) -> str:
        text = safe_thread_id(value)
        if text is None:
            raise ValueError("Session id is not valid.")
        return text

    @field_validator("comment", "turn_id", "user_message", "assistant_message")
    @classmethod
    def blank_is_missing(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None
