from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MentionKind(str, Enum):
    """What a name in the message refers to. Decides where it is looked up."""

    PLACE = "place"
    DEVELOPER = "developer"
    OTHER = "other"


class ListingSort(str, Enum):
    NEWEST = "newest"
    PRICE_LOW = "price_low"
    PRICE_HIGH = "price_high"
    SIZE_LARGE = "size_large"


class Furnishing(str, Enum):
    FURNISHED = "furnished"
    UNFURNISHED = "unfurnished"
    SEMI_FURNISHED = "semi-furnished"


class Completion(str, Enum):
    READY = "ready"
    OFF_PLAN = "off_plan"


class NameMention(BaseModel):
    """A proper name the user typed: a place, building, project, or developer."""

    text: str = Field(description="The name exactly as the user wrote it, such as 'marina' or 'JVC'.")
    kind: MentionKind = Field(
        default=MentionKind.PLACE,
        description="place for an area, community, project, or building. developer for a developer.",
    )

    @field_validator("text")
    @classmethod
    def text_required(cls, value: str) -> str:
        text = " ".join(str(value or "").split())
        if not text:
            raise ValueError("text is empty")
        return text


class ListingFilters(BaseModel):
    """Filters for properties on the market. Places and developers come from `names`."""

    property_types: list[str] = Field(
        default_factory=list,
        description="Property types as the user said them, such as apartment, villa, penthouse, office.",
    )
    bedrooms_min: int | None = Field(default=None, description="Fewest bedrooms. A studio is 0.")
    bedrooms_max: int | None = Field(default=None, description="Most bedrooms. A studio is 0.")
    price_min: float | None = Field(default=None, description="Lowest asking price in AED.")
    price_max: float | None = Field(default=None, description="Highest asking price in AED.")
    size_min_sqft: float | None = Field(default=None, description="Smallest built-up area in square feet.")
    size_max_sqft: float | None = Field(default=None, description="Largest built-up area in square feet.")
    furnishing: Furnishing | None = None
    completion: Completion | None = None
    sort: ListingSort | None = Field(default=None, description="Null when the user did not ask for an order.")

    @field_validator("bedrooms_min", "bedrooms_max", mode="before")
    @classmethod
    def whole_bedrooms(cls, value: Any) -> int | None:
        number = _number(value)
        return None if number is None or number < 0 else int(number)

    @field_validator("price_min", "price_max", "size_min_sqft", "size_max_sqft", mode="before")
    @classmethod
    def positive_amount(cls, value: Any) -> float | None:
        number = _number(value)
        return number if number is not None and number > 0 else None

    @field_validator("property_types", mode="before")
    @classmethod
    def clean_types(cls, value: Any) -> list[str]:
        if value is None:
            return []
        items = [value] if isinstance(value, str) else list(value)
        return [text for text in (" ".join(str(item or "").split()) for item in items) if text]


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
