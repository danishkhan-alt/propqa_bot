from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_CARDS = 3
MAX_FOLLOWUPS = 3


class ReplyCard(BaseModel):
    """One area or project in an advisory comparison. Listings use their own cards."""

    title: str
    tag: str = ""
    tag_color: Literal["info", "positive", "warning"] = "info"
    description: str = ""
    price: str | None = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("title is empty")
        return text


class StructuredReply(BaseModel):
    """What the answer model returns. The follow-up question is added in code.

    `intro_text` is first and required: it is streamed to the user while the rest is written.
    """

    intro_text: str = Field(description="The reply itself, in markdown.")
    message_type: Literal["recommendation", "factual_answer", "listing_results"] = "factual_answer"
    cards: list[ReplyCard] = Field(default_factory=list)
    exclusions_note: str = ""
    data_source_note: str = ""
    suggested_followups: list[str] = Field(default_factory=list)

    @field_validator("cards")
    @classmethod
    def cap_cards(cls, value: list[ReplyCard]) -> list[ReplyCard]:
        return value[:MAX_CARDS]

    @field_validator("suggested_followups")
    @classmethod
    def cap_followups(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned[:MAX_FOLLOWUPS]
