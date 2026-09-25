from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent.enums.routing import Intent, Route, TurnKind
from agent.schemas.listing import ListingFilters, NameMention
from agent.schemas.profile import ProfileSignals


class QueryRoute(BaseModel):
    """Structured decision from the query router. There is no clarify route."""

    route: Route
    turn_kind: TurnKind
    intent: Intent = Field(
        default=Intent.OTHER,
        description=(
            "list, lookup, aggregate, trend, compare, rank, assess, or other. "
            "list and rank mean the user wants rows."
        ),
    )
    purpose: str | None = Field(
        default=None,
        description=(
            "sale, rent, or whatever the user stated. Null when neither this message nor the "
            "previous lookup says; 'properties in Marina' states no purpose."
        ),
    )
    limit: int | None = Field(
        default=None,
        description="Row count the user asked for, or carried from the previous lookup. Null when no count was given.",
    )
    order: str | None = Field(
        default=None,
        description="How to order rows, in the user's words. Null when they did not say.",
    )
    seeking_advice: bool = Field(
        default=False,
        description=(
            "True when the user is choosing what or where to buy, or whether to buy, "
            "and their goal, budget, or timeline would change the answer."
        ),
    )
    profile: ProfileSignals = Field(
        default_factory=ProfileSignals,
        description="Buyer facts stated in this message only.",
    )
    names: list[NameMention] = Field(
        default_factory=list,
        description="Places, buildings, projects, and developers the lookup is about, as the user wrote them.",
    )
    listing_filters: ListingFilters | None = Field(
        default=None,
        description="Set only when the user wants to see properties for sale or rent. Null otherwise.",
    )
    confidence: float = Field(ge=0, le=1, description="0 to 1. How sure this route is.")
    rationale: str = Field(description="One sentence explaining the route. No user data beyond the ask.")

    @field_validator("purpose", "order", mode="before")
    @classmethod
    def blank_text_to_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("limit", mode="before")
    @classmethod
    def coerce_limit(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.3
        return min(1.0, max(0.0, number))


class DomainRoute(BaseModel):
    """Structured decision from the domain router. Ids must exist in the catalog index."""

    domain_ids: list[str] = Field(description="Primary catalog packs, most relevant first. At most 2.")
    join_ids: list[str] = Field(
        default_factory=list,
        description="Packs needed only as join keys, usually locations. Not a duplicate of domain_ids.",
    )
    confidence: float = Field(ge=0, le=1)
    rationale: str

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.3
        return min(1.0, max(0.0, number))

    @field_validator("domain_ids", "join_ids", mode="before")
    @classmethod
    def coerce_ids(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return list(value)


class Assumptions(BaseModel):
    """Purpose and order come from the query router. A list also carries a page window."""

    purpose: str | None = None
    limit: int | None = None
    order: str | None = None
    page: int | None = None


class LastNeedDb(BaseModel):
    """Compact memory of the last warehouse turn. No SQL text and no row grid."""

    domain_ids: list[str]
    join_ids: list[str] = Field(default_factory=list)
    intent_summary: str = ""
    result_meta: dict[str, Any] = Field(default_factory=dict)


def checkpoint_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Redis stores these models as LangChain constructor envelopes.

    The fields live under ``kwargs``. A plain dict is already the payload.
    """
    if value.get("lc") in (1, 2) and value.get("type") == "constructor":
        kwargs = value.get("kwargs")
        if isinstance(kwargs, dict):
            return kwargs
    return value


def as_query_route(value: QueryRoute | dict[str, Any] | None) -> QueryRoute | None:
    if value is None:
        return None
    if isinstance(value, QueryRoute):
        return value
    return QueryRoute.model_validate(checkpoint_payload(value))


def as_domain_route(value: DomainRoute | dict[str, Any] | None) -> DomainRoute | None:
    if value is None:
        return None
    if isinstance(value, DomainRoute):
        return value
    return DomainRoute.model_validate(checkpoint_payload(value))


def as_assumptions(value: Assumptions | dict[str, Any] | None) -> Assumptions | None:
    if value is None:
        return None
    if isinstance(value, Assumptions):
        return value
    return Assumptions.model_validate(checkpoint_payload(value))


def as_last_need_db(value: LastNeedDb | dict[str, Any] | None) -> LastNeedDb | None:
    if value is None:
        return None
    if isinstance(value, LastNeedDb):
        return value
    return LastNeedDb.model_validate(checkpoint_payload(value))
