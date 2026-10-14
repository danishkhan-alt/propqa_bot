"""Warehouse-free checks for the listing scorer."""

from evals.listing_score import TurnOutcome, score_listing_result


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
