from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from agent.enums.listing import Completion, Furnishing, ListingPurpose, ListingSort, MentionKind, NearStation


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


# A short walk to the platform, when the user asks for "near the metro" without a distance.
DEFAULT_STATION_KM = 1.0
MAX_STATION_KM = 5.0
# Smallest property value that qualifies an owner for the 10-year UAE Golden Visa. Only a
# property bought counts; a tenancy never does.
GOLDEN_VISA_MIN_PRICE_AED = 2_000_000


class ListingFilters(BaseModel):
    """Filters for properties on the market. Places and developers come from `names`."""

    purpose: ListingPurpose = Field(
        default=ListingPurpose.ANY,
        description="sale or rent only when the user said so. any when they did not.",
    )
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
    furnishing: Furnishing = Furnishing.ANY
    completion: Completion = Completion.ANY
    sort: ListingSort = Field(default=ListingSort.NEWEST, description="newest when the user did not ask for an order.")
    # Not nullable: the router's output schema is near its limit of nullable fields.
    near_station: NearStation = Field(
        default=NearStation.ANY,
        description="metro or tram when they want homes near one, metro_or_tram for public transport. any otherwise.",
    )
    station_within_km: float = Field(
        default=0,
        description="How close to the station, in km, when they said it ('within 500 m' is 0.5). 0 when they did not.",
    )
    golden_visa: bool = Field(
        default=False,
        description="True when they want properties that qualify for the UAE Golden Visa. False otherwise.",
    )

    @model_validator(mode="after")
    def golden_visa_is_a_purchase(self) -> "ListingFilters":
        # The price floor is a hard condition in the query, so loosening a price range never drops it.
        if self.golden_visa:
            self.purpose = ListingPurpose.SALE
        return self

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

    @field_validator("station_within_km", mode="before")
    @classmethod
    def station_distance(cls, value: Any) -> float:
        number = _number(value)
        return min(number, MAX_STATION_KM) if number is not None and number > 0 else 0

    @property
    def station_km(self) -> float:
        """The distance a station filter applies: what they said, else a short walk."""
        return self.station_within_km or DEFAULT_STATION_KM

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
