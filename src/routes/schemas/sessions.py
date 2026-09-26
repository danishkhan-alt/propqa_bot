"""Request bodies for the session and preference routes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NewSessionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    previous_session_id: str | None = None
    user_id: str | None = None
    carry_over_long_term: bool = True


class ForgetSessionsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    session_ids: list[str] = Field(default_factory=list)
    guest_user_id: str | None = None
    merge_ltm: bool = True


class SavePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    preferences: dict = Field(default_factory=dict)
