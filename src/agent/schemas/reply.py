from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_CARDS = 3
MAX_FOLLOWUPS = 3
MAX_FIGURE_COLUMNS = 4
MAX_EXPLAINER_POINTS = 6


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


FigureUnit = Literal[
    "aed", "aed_per_sqft", "sqft", "percent", "change", "fraction", "count", "number", "year", "text"
]


class FigureColumn(BaseModel):
    """One column of the lookup rows to show, named the way a buyer would read it."""

    column: str
    label: str
    unit: FigureUnit = "number"


class FigureSeries(BaseModel):
    """One value of series_column, shown as its own column or line."""

    value: str
    label: str


class FigureSpec(BaseModel):
    """Which rows and columns to lay out. The model picks them; code copies the values.

    stats: one row, its figures as tiles. table: a few rows side by side.
    bar: one figure compared across rows, each row named by label_column.
    line: one to three figures over periods, each row a period named by label_column.

    Rows with two dimensions (one per year and bedroom count) name the second one in
    series_column; code turns the first figure into one column or line per series value.
    """

    layout: Literal["none", "stats", "table", "bar", "line"] = "none"
    label_column: str = ""
    label_title: str = ""
    columns: list[FigureColumn] = Field(default_factory=list)
    series_column: str = ""
    series: list[FigureSeries] = Field(default_factory=list)

    @field_validator("columns", "series")
    @classmethod
    def cap_columns(cls, value: list) -> list:
        return value[:MAX_FIGURE_COLUMNS]


class Explainer(BaseModel):
    """A short written aid: ordered steps, pros and cons, or one callout."""

    kind: Literal["none", "steps", "pros_cons", "callout"] = "none"
    title: str = ""
    points: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)

    @field_validator("points", "cautions")
    @classmethod
    def cap_points(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        return cleaned[:MAX_EXPLAINER_POINTS]


class StructuredReply(BaseModel):
    """What the answer model returns. The follow-up question is added in code.

    `intro_text` is first and required: it is streamed to the user while the rest is written.
    """

    intro_text: str = Field(description="The reply itself, in markdown.")
    message_type: Literal["recommendation", "factual_answer", "explanation", "listing_results"] = (
        "factual_answer"
    )
    cards: list[ReplyCard] = Field(default_factory=list)
    figures: FigureSpec | None = None
    explainer: Explainer | None = None
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
