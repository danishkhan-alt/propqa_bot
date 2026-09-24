from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ReplyCard(BaseModel):
    """One area card now. A listing card can reuse the same fields later."""

    title: str
    tag: str = ""
    tag_color: Literal["info", "positive", "warning"] = "info"
    description: str = ""
    image_url: str | None = None
    price: str | None = None

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("title is empty")
        return text


class StructuredReply(BaseModel):
    """What the answer model returns. Clarifying questions are added in code."""

    message_type: Literal["recommendation", "factual_answer", "listing_results"] = "factual_answer"
    intro_text: str = ""
    data_source_note: str = ""
    cards: list[ReplyCard] = Field(default_factory=list)
    exclusions_note: str = ""
    suggested_followups: list[str] = Field(default_factory=list)

    @field_validator("cards")
    @classmethod
    def cap_cards(cls, value: list[ReplyCard]) -> list[ReplyCard]:
        return value[:3]

    @field_validator("suggested_followups")
    @classmethod
    def cap_followups(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned[:2]
