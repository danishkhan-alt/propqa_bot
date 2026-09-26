"""Buyer profile: keep what the user told us, and pick at most one question to ask next.

Questions are a fixed catalog so the UI can render tap options and the answers stay a
closed set. The router reads profile facts from free text; this module only merges them.
"""

from __future__ import annotations

from typing import Any

from agent.enums.routing import Intent, Route
from agent.schemas.profile import (
    BUDGET_RANGES,
    GOALS,
    TIMELINES,
    ProfileAnswerOption,
    ProfileQuestion,
    ProfileSignals,
    parse_family_size,
)
from agent.schemas.routes import QueryRoute

PROFILE_KEYS = ("family_size", "goal", "budget_range", "timeline")

_ALLOWED_VALUES_BY_PROFILE_KEY = {
    "goal": GOALS,
    "budget_range": BUDGET_RANGES,
    "timeline": TIMELINES,
}
# A shortlist of these shapes gets better when we know the buyer's situation.
_SHORTLIST_INTENTS = frozenset(
    {Intent.LIST, Intent.RANK, Intent.COMPARE, Intent.ASSESS}
)


PROFILE_QUESTIONS: tuple[ProfileQuestion, ...] = (
    ProfileQuestion(
        id="goal",
        prompt="Is this a home for you, or an investment? It changes which of these I'd put first.",
        options=(
            ProfileAnswerOption(
                "live", "A home for me", "It's a home for me to live in."
            ),
            ProfileAnswerOption(
                "invest", "An investment", "I'm buying it as an investment."
            ),
            ProfileAnswerOption(
                "both",
                "A bit of both",
                "A bit of both: I'll live in it, and it should hold its value.",
            ),
        ),
    ),
    ProfileQuestion(
        id="budget_range",
        prompt="What budget are you working with?",
        options=(
            ProfileAnswerOption(
                "under_1m", "Under AED 1M", "My budget is under AED 1M."
            ),
            ProfileAnswerOption("1m_2m", "AED 1M–2M", "My budget is AED 1M to 2M."),
            ProfileAnswerOption("2m_4m", "AED 2M–4M", "My budget is AED 2M to 4M."),
            ProfileAnswerOption("4m_plus", "AED 4M+", "My budget is above AED 4M."),
        ),
    ),
    ProfileQuestion(
        id="timeline",
        prompt="Do you want to move in soon, or are you open to off-plan?",
        options=(
            ProfileAnswerOption(
                "ready", "Ready to move in", "I want something ready to move into."
            ),
            ProfileAnswerOption(
                "off_plan", "Open to off-plan", "I'm open to off-plan."
            ),
        ),
    ),
)


def sanitize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Known keys with valid values only. The UI sends this, so it is not trusted."""
    profile: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if key == "family_size":
            size = parse_family_size(value)
            if size is not None:
                profile[key] = size
        elif (
            key in _ALLOWED_VALUES_BY_PROFILE_KEY
            and value in _ALLOWED_VALUES_BY_PROFILE_KEY[key]
        ):
            profile[key] = value
    return profile


def merge_profile(
    existing: dict[str, Any] | None, signals: ProfileSignals | None
) -> dict[str, Any]:
    """What the user says this turn replaces what we knew."""
    profile = sanitize_profile(existing)
    if signals is not None:
        profile.update(sanitize_profile(signals.model_dump(exclude_none=True)))
    return {key: profile[key] for key in PROFILE_KEYS if key in profile}


def pick_next_profile_question(
    route: QueryRoute | None,
    profile: dict[str, Any],
    asked: list[str] | None,
    *,
    has_listings: bool,
) -> ProfileQuestion | None:
    """At most one question, each asked once per thread, and only where the answer would change."""
    if route is None or not _should_ask_profile_question(
        route, has_listings=has_listings
    ):
        return None
    already = set(asked or [])
    for question in PROFILE_QUESTIONS:
        if question.id in profile or question.id in already:
            continue
        return question
    return None


def _should_ask_profile_question(route: QueryRoute, *, has_listings: bool) -> bool:
    # The catalog is for buyers. Rent budgets and "live or invest" do not apply to a tenant.
    if "rent" in str(route.purpose or "").lower():
        return False
    if route.seeking_advice:
        return True
    return (
        route.route is Route.NEED_DB
        and route.intent in _SHORTLIST_INTENTS
        and has_listings
    )
