"""Reply numbers match the lookup. No model and no warehouse."""

from agent.reply.grounding_check import ungrounded_numbers
from agent.schemas.listing import GOLDEN_VISA_MIN_PRICE_AED


def test_a_rounded_price_matches_the_row():
    flags = ungrounded_numbers(
        "The average sale price is AED 1.2M.",
        rows=[{"actual_worth": 1195000}],
    )
    assert flags == []


def test_a_count_copied_from_listing_count_is_allowed():
    flags = ungrounded_numbers(
        "There are 13 apartments in this search.",
        listings=[{"title": "Marina Gate", "bedrooms": 2}],
        listing_count=13,
    )
    assert flags == []


def test_a_number_with_no_source_is_flagged():
    flags = ungrounded_numbers(
        "Prices start at AED 900,000.",
        rows=[{"asking_price_aed": 1500000}],
    )
    assert len(flags) == 1
    assert "AED 900,000" in flags[0]
    assert "not in the rows" in flags[0]


def test_the_golden_visa_minimum_is_allowed_on_a_visa_reply():
    flags = ungrounded_numbers(
        f"A Golden Visa needs a property worth at least AED {GOLDEN_VISA_MIN_PRICE_AED:,}.",
    )
    assert flags == []
