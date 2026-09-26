"""Buyer facts the router reads from one message. Each value is a closed set the UI also knows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field, field_validator

Goal = Literal["live", "invest", "both"]
BudgetRange = Literal["under_1m", "1m_2m", "2m_4m", "4m_plus"]
Timeline = Literal["ready", "off_plan"]

GOALS = frozenset(get_args(Goal))
BUDGET_RANGES = frozenset(get_args(BudgetRange))
TIMELINES = frozenset(get_args(Timeline))
MAX_FAMILY_SIZE = 20


class ProfileSignals(BaseModel):
    """Only what this message states. A field stays null when the message does not say it."""

    goal: Goal | None = Field(
        default=None,
        description="live (a home for them or their family), invest (rental income or growth), or both.",
    )
    budget_range: BudgetRange | None = Field(
        default=None,
        description=(
            "The bucket holding their maximum purchase budget in AED. "
            "under_1m, 1m_2m, 2m_4m, or 4m_plus. 'Under 2M' is 1m_2m. Null for a rent budget."
        ),
    )
    timeline: Timeline | None = Field(
        default=None,
        description="ready (move in now) or off_plan (willing to wait for handover).",
    )
    family_size: int | None = Field(
        default=None,
        description="People in the household when they say it. 'Family of four' is 4.",
    )

    @field_validator("goal", "budget_range", "timeline", mode="before")
    @classmethod
    def unknown_to_none(cls, value: Any, info) -> str | None:
        allowed = {"goal": GOALS, "budget_range": BUDGET_RANGES, "timeline": TIMELINES}[info.field_name]
        text = str(value).strip() if value is not None else ""
        return text if text in allowed else None

    @field_validator("family_size", mode="before")
    @classmethod
    def sane_family_size(cls, value: Any) -> int | None:
        return parse_family_size(value)


def parse_family_size(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= MAX_FAMILY_SIZE else None


@dataclass(frozen=True)
class ProfileAnswerOption:
    id: str
    label: str
    reply: str


@dataclass(frozen=True)
class ProfileQuestion:
    id: str
    prompt: str
    options: tuple[ProfileAnswerOption, ...]

    def to_ui_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "options": [
                {"id": option.id, "label": option.label, "reply": option.reply}
                for option in self.options
            ],
        }
