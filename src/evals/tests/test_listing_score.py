"""Warehouse-free checks for the listing scorer."""

import re

import pytest

from evals.listing_score import TurnOutcome, score_listing_result, supported_as_listing_total


def _outcome(**overrides) -> TurnOutcome:
    outcome = TurnOutcome(
        listing_ids=["101"],
        total=1,
        reply="One apartment in Dubai Marina.",
        route={"limit": 10},
    )
    for key, value in overrides.items():
        setattr(outcome, key, value)
    return outcome


def _matching_fact(listing_id: str = "101") -> dict:
    return {"id": listing_id, "matches_filters": True, "place_links": ["v2"], "asking_price_aed": 1500000}


def test_an_id_outside_the_truth_set_fails():
    passed, detail = score_listing_result(
        {},
        _outcome(),
        truth=set(),
        relaxed=False,
        facts=[_matching_fact()],
        unsupported_claims=[],
    )
    assert not passed
    assert "wrong_ids=101" in detail


def test_a_returned_row_that_breaks_the_filters_fails():
    fact = _matching_fact()
    fact["matches_filters"] = False
    passed, detail = score_listing_result(
        {},
        _outcome(),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=[],
    )
    assert not passed
    assert "broke_filters=101" in detail


def test_a_relaxed_search_with_an_empty_note_fails():
    passed, detail = score_listing_result(
        {},
        _outcome(notes=[]),
        truth={"101"},
        relaxed=True,
        facts=[_matching_fact()],
        unsupported_claims=[],
    )
    assert not passed
    assert "missing relaxation note" in detail


def test_an_unsupported_price_fails():
    passed, detail = score_listing_result(
        {},
        _outcome(),
        truth={"101"},
        relaxed=False,
        facts=[_matching_fact()],
        unsupported_claims=["AED 900,000 asking price"],
    )
    assert not passed
    assert "AED 900,000 asking price" in detail


def test_a_count_that_matches_the_inventory_total_passes():
    ids = [str(number) for number in range(101, 111)]
    facts = [_matching_fact(listing_id) for listing_id in ids]
    facts[0]["rooms"] = 2
    passed, detail = score_listing_result(
        {},
        _outcome(
            listing_ids=ids,
            total=13,
            reply="There are 13 two-bedroom apartments for sale in JVC under AED 1.5M.",
        ),
        truth={str(number) for number in range(101, 114)},
        relaxed=False,
        facts=facts,
        unsupported_claims=["There are 13 two-bedroom apartments for sale in JVC under AED 1.5M"],
    )
    assert passed, detail


def test_a_page_count_without_an_inventory_total_fails():
    passed, detail = score_listing_result(
        {},
        _outcome(reply="Dubai Marina has 50 active listings.", total=None),
        truth={"101"},
        relaxed=False,
        facts=[_matching_fact()],
        unsupported_claims=["Dubai Marina has 50 active listings"],
    )
    assert not passed
    assert "50 active listings" in detail


def test_an_off_plan_claim_on_the_sheet_passes():
    fact = _matching_fact()
    fact["completion"] = "off_plan"
    fact["title"] = "LIV LUX"
    passed, detail = score_listing_result(
        {},
        _outcome(reply="LIV LUX is off-plan."),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["LIV LUX is off-plan"],
    )
    assert passed, detail


def test_a_furnished_claim_on_the_sheet_passes():
    fact = _matching_fact()
    fact["furnished"] = "yes"
    passed, detail = score_listing_result(
        {},
        _outcome(reply="Dana Tower is furnished."),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["Dana Tower is furnished"],
    )
    assert passed, detail


def test_a_type_on_the_sheet_with_no_price_passes():
    fact = _matching_fact()
    fact["categories"] = ["Hotel Apartment", "Residential"]
    fact["purpose"] = "for_rent"
    fact["community"] = "Downtown Dubai"
    passed, detail = score_listing_result(
        {},
        _outcome(reply="larger hotel apartments for rent"),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["larger hotel apartments for rent"],
    )
    assert passed, detail


def test_a_place_that_is_not_on_the_sheet_fails():
    fact = _matching_fact()
    fact["community"] = "Downtown Dubai"
    fact["address"] = "Downtown Dubai, Dubai"
    passed, detail = score_listing_result(
        {},
        _outcome(reply="These are in Jebel Ali."),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["These are in Jebel Ali"],
    )
    assert not passed
    assert "Jebel Ali" in detail


def test_a_ready_claim_on_the_sheet_passes():
    fact = _matching_fact()
    fact["completion"] = "ready"
    fact["community"] = "Downtown Dubai"
    passed, detail = score_listing_result(
        {},
        _outcome(reply="Most of these properties are already ready to move into."),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["Most of these properties are already ready to move into"],
    )
    assert passed, detail


def test_a_rounded_rent_on_the_sheet_passes():
    fact = _matching_fact()
    fact["rent_aed"] = 5999
    fact["purpose"] = "for_rent"
    passed, detail = score_listing_result(
        {},
        _outcome(reply="rent of around AED 6,000 monthly"),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["rent of around AED 6,000 monthly"],
    )
    assert passed, detail


def test_a_tower_number_is_not_treated_as_a_price():
    fact = _matching_fact()
    fact["title"] = "Mag 218 Tower"
    fact["furnished"] = "furnished"
    fact["purpose"] = "for_rent"
    fact["rent_aed"] = 5999
    fact["rooms"] = 1
    passed, detail = score_listing_result(
        {},
        _outcome(reply="Mag 218 Tower 1-bed furnished apartment for rent at around AED 6,000/month"),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=["Mag 218 Tower 1-bed furnished apartment for rent at around AED 6,000/month"],
    )
    assert passed, detail


def _ocean_heights_rent() -> dict:
    fact = _matching_fact()
    fact["building"] = "Ocean Heights"
    fact["rooms"] = 1
    fact["purpose"] = "for_rent"
    fact["rent_aed"] = 360000
    fact["rental_period"] = "yearly"
    return fact


def test_a_monthly_reading_of_a_yearly_rent_passes():
    claim = "Ocean Heights 1-bed apartment rent at AED 30,000/month"
    passed, detail = score_listing_result(
        {},
        _outcome(reply=claim),
        truth={"101"},
        relaxed=False,
        facts=[_ocean_heights_rent()],
        unsupported_claims=[claim],
    )
    assert passed, detail


def test_a_made_up_monthly_rent_fails():
    claim = "Ocean Heights rent at AED 99,000/month"
    passed, detail = score_listing_result(
        {},
        _outcome(reply=claim),
        truth={"101"},
        relaxed=False,
        facts=[_ocean_heights_rent()],
        unsupported_claims=[claim],
    )
    assert not passed
    assert claim in detail


def test_a_building_that_was_not_returned_fails():
    claim = "Palm Tower rent at AED 30,000/month"
    passed, detail = score_listing_result(
        {},
        _outcome(reply=claim),
        truth={"101"},
        relaxed=False,
        facts=[_ocean_heights_rent()],
        unsupported_claims=[claim],
    )
    assert not passed
    assert claim in detail


_INVENTORY_TOTAL = 176
_PAGE_LENGTH = 10


def _span(text: str, raw: str):
    return re.search(rf"(?<![\d,]){re.escape(raw)}(?![\d,])", text)


@pytest.mark.parametrize(
    ("text", "raw", "expected"),
    [
        ("The number of properties in Dubai Marina is 176.", "176", True),
        ("Dubai Marina has a total of 176 listings.", "176", True),
        ("176 properties match in Dubai Marina.", "176", True),
        ("Here are 10 of the 176 properties.", "10", True),
        ("There are 10 properties in Dubai Marina.", "10", False),
        ("The number of properties in Dubai Marina is 10.", "10", False),
        ("The number of properties is 1,176.", "1,176", False),
        ("Prices start at AED 176.", "176", False),
        ("A 176 sq ft studio.", "176", False),
    ],
)
def test_supported_as_listing_total(text, raw, expected):
    match = _span(text, raw)
    assert match is not None
    assert (
        supported_as_listing_total(text, match.start(), match.end(), _INVENTORY_TOTAL, _PAGE_LENGTH)
        is expected
    )


def _marina_page() -> tuple[list[str], list[dict]]:
    ids = [str(number) for number in range(1, 11)]
    facts = []
    for listing_id in ids:
        fact = _matching_fact(listing_id)
        fact["community"] = "Dubai Marina"
        facts.append(fact)
    return ids, facts


def test_an_inventory_total_after_the_noun_passes():
    claim = "number of properties in Dubai Marina is 176"
    ids, facts = _marina_page()
    passed, detail = score_listing_result(
        {},
        _outcome(listing_ids=ids, total=176, reply=claim),
        truth={str(number) for number in range(1, 177)},
        relaxed=False,
        facts=facts,
        unsupported_claims=[claim],
    )
    assert passed, detail


def test_a_page_size_stated_as_the_total_fails():
    claim = "number of properties in Dubai Marina is 10"
    ids, facts = _marina_page()
    passed, detail = score_listing_result(
        {},
        _outcome(listing_ids=ids, total=176, reply=claim),
        truth={str(number) for number in range(1, 177)},
        relaxed=False,
        facts=facts,
        unsupported_claims=[claim],
    )
    assert not passed
    assert claim in detail


def test_a_bedroom_shorthand_and_a_million_range_pass():
    claim = "Aeternitas Tower 2 B/R for Sale priced around AED 4.24 to 4.25 million"
    fact = _matching_fact()
    fact["building"] = "Aeternitas Tower"
    fact["rooms"] = 2
    fact["asking_price_aed"] = 4_240_000
    fact["asking_price_max_aed"] = 4_250_000
    passed, detail = score_listing_result(
        {},
        _outcome(reply=claim),
        truth={"101"},
        relaxed=False,
        facts=[fact],
        unsupported_claims=[claim],
    )
    assert passed, detail


def test_a_reply_that_copies_the_wrong_total_still_fails():
    claim = "number of properties in Dubai Marina is 176"
    passed, detail = score_listing_result(
        {},
        _outcome(listing_ids=["101"], total=176, reply=claim),
        truth={"101"},
        relaxed=False,
        facts=[_matching_fact()],
        unsupported_claims=[claim],
    )
    assert not passed
    assert "total_mismatch" in detail


def test_a_page_inside_the_truth_set_passes():
    passed, detail = score_listing_result(
        {},
        _outcome(notes=["No listing matched the price range, so these results ignore price."]),
        truth={"101"},
        relaxed=True,
        facts=[_matching_fact()],
        unsupported_claims=[],
    )
    assert passed, detail
