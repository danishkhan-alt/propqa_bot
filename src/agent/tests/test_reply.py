"""Buyer profile, listing cards, and the streamed structured reply."""

from __future__ import annotations

import pytest

from agent.enums.routing import Intent, Route, TurnKind
from agent.reply.clarify import merge_profile, next_question
from agent.schemas.profile import ProfileSignals
from agent.schemas.reply import StructuredReply
from agent.schemas.routes import QueryRoute
from agent.services.llm import REPLY_FALLBACK, stream_structured_reply
from agent.sql.cards import listing_cards, listing_facts


def _route(**fields) -> QueryRoute:
    base = {
        "route": Route.NEED_DB,
        "turn_kind": TurnKind.NEW,
        "intent": Intent.LIST,
        "purpose": "sale",
        "confidence": 0.9,
        "rationale": "test",
    }
    return QueryRoute(**{**base, **fields})


# Profile


def test_what_the_user_says_now_replaces_what_we_knew():
    profile = merge_profile(
        {"goal": "live", "budget_range": "under_1m"},
        ProfileSignals(budget_range="2m_4m", family_size=4),
    )
    assert profile == {"family_size": 4, "goal": "live", "budget_range": "2m_4m"}


def test_unknown_values_never_enter_the_profile():
    assert ProfileSignals(goal="flip", budget_range="huge", family_size=0).model_dump() == {
        "goal": None,
        "budget_range": None,
        "timeline": None,
        "family_size": None,
    }
    assert merge_profile({"goal": "flip", "timeline": "ready", "extra": 1}, None) == {"timeline": "ready"}


# Questions


def test_a_shortlist_asks_the_first_missing_fact():
    question = next_question(_route(), {"goal": "invest"}, [], has_listings=True)
    assert question is not None and question.id == "budget_range"


def test_a_question_already_asked_is_not_asked_again():
    question = next_question(_route(), {}, ["goal", "budget_range"], has_listings=True)
    assert question is not None and question.id == "timeline"
    assert next_question(_route(), {}, ["goal", "budget_range", "timeline"], has_listings=True) is None


@pytest.mark.parametrize(
    ("route", "has_listings"),
    [
        (_route(intent=Intent.AGGREGATE), False),
        (_route(), False),
        (_route(purpose="rent", seeking_advice=True), True),
        (_route(route=Route.DIRECT_ANSWER, intent=Intent.OTHER), False),
    ],
)
def test_no_question_when_it_would_not_change_the_answer(route, has_listings):
    assert next_question(route, {}, [], has_listings=has_listings) is None


def test_advice_without_listings_still_asks():
    route = _route(route=Route.DIRECT_ANSWER, intent=Intent.OTHER, seeking_advice=True)
    question = next_question(route, {}, [], has_listings=False)
    assert question is not None and question.id == "goal"
    assert all(option["reply"] for option in question.payload()["options"])


# Listing cards


def _row(**fields) -> dict:
    return {
        "id": 7,
        "title_en": "Harbour View",
        "purpose": "for_sale",
        "show_price": True,
        "price_min": "1200000.0000",
        "area": "812.50",
        "images": ["https://cdn.test/1.jpg", None, "https://cdn.test/2.jpg"],
        "agency_company": None,
        "agency_user_name": "Keys Realty",
        **fields,
    }


def test_cards_keep_id_order_and_fill_what_the_loader_found():
    cards = listing_cards(["9", "7", "abc"], lambda ids: [_row()])
    assert [card["id"] for card in cards] == ["9", "7", "abc"]
    assert cards[0] == {"id": "9"}
    assert cards[1]["images"] == ["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"]
    assert cards[1]["image_url"] == "https://cdn.test/1.jpg"
    assert cards[1]["agency_name"] == "Keys Realty"


def test_a_hidden_price_is_never_shown():
    card = listing_cards(["7"], lambda ids: [_row(show_price=False)])[0]
    assert "price_min" not in card
    assert "asking_price_aed" not in listing_facts([card])[0]


def test_a_loader_failure_still_returns_id_cards():
    def broken(ids):
        raise RuntimeError("warehouse down")

    assert listing_cards(["7"], broken) == [{"id": "7"}]


def test_facts_are_numbers_and_leave_out_media():
    facts = listing_facts(listing_cards(["7"], lambda ids: [_row()]))
    assert facts == [
        {
            "property_id": "7",
            "title": "Harbour View",
            "size_sqft": 812.5,
            "purpose": "for_sale",
            "asking_price_aed": 1200000,
            "agency": "Keys Realty",
        }
    ]


def test_rent_is_read_from_the_listed_period():
    card = listing_cards(
        ["7"],
        lambda ids: [_row(purpose="for_rent", rental_period="monthly", monthly_price="9500", price_min=None)],
    )[0]
    assert listing_facts([card])[0]["rent_aed"] == {"amount": 9500, "period": "monthly"}


# Streaming


class _Stream:
    def __init__(self, partials, *, fail_after: int | None = None, final=None) -> None:
        self.partials = partials
        self.fail_after = fail_after
        self.final = final

    def stream(self, messages, config=None):
        for index, partial in enumerate(self.partials):
            if self.fail_after is not None and index == self.fail_after:
                raise RuntimeError("connection reset")
            yield partial

    def invoke(self, messages, config=None):
        if self.final is None:
            raise RuntimeError("still down")
        return self.final


def test_intro_text_streams_as_it_grows():
    shown: list[str] = []
    runnable = _Stream(
        [
            {"intro_text": "Two"},
            {"intro_text": "Two homes"},
            {"intro_text": "Two homes"},
            {"intro_text": "Two homes fit.", "suggested_followups": ["Compare with JVC"]},
        ]
    )
    reply = stream_structured_reply(runnable, [], None, shown.append)
    assert shown == ["Two", " homes", " fit."]
    assert reply.suggested_followups == ["Compare with JVC"]


def test_a_broken_stream_keeps_the_text_already_shown():
    shown: list[str] = []
    runnable = _Stream([{"intro_text": "Two homes"}, {"intro_text": "Two homes fit."}], fail_after=1)
    reply = stream_structured_reply(runnable, [], None, shown.append)
    assert shown == ["Two homes"]
    assert reply == StructuredReply(intro_text="Two homes")


def test_a_stream_that_shows_nothing_falls_back_to_one_call():
    shown: list[str] = []
    runnable = _Stream([], fail_after=0, final={"intro_text": "Here it is."})
    reply = stream_structured_reply(runnable, [], None, shown.append)
    assert shown == ["Here it is."]
    assert reply.intro_text == "Here it is."


def test_the_fallback_reply_is_used_when_every_attempt_fails():
    shown: list[str] = []
    reply = stream_structured_reply(_Stream([], fail_after=0), [], None, shown.append)
    assert reply == REPLY_FALLBACK
    assert shown == [REPLY_FALLBACK.intro_text]
