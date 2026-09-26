"""Buyer profile, listing cards, and the streamed structured reply."""

from __future__ import annotations

import anthropic
import httpx
import pytest

from agent.enums.routing import Intent, Route, TurnKind
from agent.reply.buyer_profile import merge_profile, pick_next_profile_question
from agent.reply.figures import build_explainer, build_figures, build_reply_blocks, format_figure
from agent.schemas.profile import ProfileSignals
from agent.schemas.reply import (
    Explainer,
    FigureColumn,
    FigureSeries,
    FigureSpec,
    ReplyCard,
    StructuredReply,
)
from agent.schemas.routes import QueryRoute
from agent.services.llm import REPLY_FALLBACK, stream_structured_reply_with_fallback
from agent.sql.cards import fetch_listing_cards, prompt_listing_facts


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
    question = pick_next_profile_question(_route(), {"goal": "invest"}, [], has_listings=True)
    assert question is not None and question.id == "budget_range"


def test_a_question_already_asked_is_not_asked_again():
    question = pick_next_profile_question(_route(), {}, ["goal", "budget_range"], has_listings=True)
    assert question is not None and question.id == "timeline"
    assert pick_next_profile_question(_route(), {}, ["goal", "budget_range", "timeline"], has_listings=True) is None


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
    assert pick_next_profile_question(route, {}, [], has_listings=has_listings) is None


def test_advice_without_listings_still_asks():
    route = _route(route=Route.DIRECT_ANSWER, intent=Intent.OTHER, seeking_advice=True)
    question = pick_next_profile_question(route, {}, [], has_listings=False)
    assert question is not None and question.id == "goal"
    assert all(option["reply"] for option in question.to_ui_payload()["options"])


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
    cards = fetch_listing_cards(["9", "7", "abc"], lambda ids: [_row()])
    assert [card["id"] for card in cards] == ["9", "7", "abc"]
    assert cards[0] == {"id": "9"}
    assert cards[1]["images"] == ["https://cdn.test/1.jpg", "https://cdn.test/2.jpg"]
    assert cards[1]["image_url"] == "https://cdn.test/1.jpg"
    assert cards[1]["agency_name"] == "Keys Realty"


def test_a_hidden_price_is_never_shown():
    card = fetch_listing_cards(["7"], lambda ids: [_row(show_price=False)])[0]
    assert "price_min" not in card
    assert "asking_price_aed" not in prompt_listing_facts([card])[0]


def test_a_loader_failure_still_returns_id_cards():
    def broken(ids):
        raise RuntimeError("warehouse down")

    assert fetch_listing_cards(["7"], broken) == [{"id": "7"}]


def test_facts_are_numbers_and_leave_out_media():
    facts = prompt_listing_facts(fetch_listing_cards(["7"], lambda ids: [_row()]))
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
    card = fetch_listing_cards(
        ["7"],
        lambda ids: [_row(purpose="for_rent", rental_period="monthly", monthly_price="9500", price_min=None)],
    )[0]
    assert prompt_listing_facts([card])[0]["rent_aed"] == {"amount": 9500, "period": "monthly"}


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
    reply = stream_structured_reply_with_fallback(runnable, [], None, shown.append)
    assert shown == ["Two", " homes", " fit."]
    assert reply.suggested_followups == ["Compare with JVC"]


def test_a_broken_stream_keeps_the_text_already_shown():
    shown: list[str] = []
    runnable = _Stream([{"intro_text": "Two homes"}, {"intro_text": "Two homes fit."}], fail_after=1)
    reply = stream_structured_reply_with_fallback(runnable, [], None, shown.append)
    assert shown == ["Two homes"]
    assert reply == StructuredReply(intro_text="Two homes")


def test_a_stream_that_shows_nothing_falls_back_to_one_call():
    shown: list[str] = []
    runnable = _Stream([], fail_after=0, final={"intro_text": "Here it is."})
    reply = stream_structured_reply_with_fallback(runnable, [], None, shown.append)
    assert shown == ["Here it is."]
    assert reply.intro_text == "Here it is."


def test_a_rejected_stream_is_not_sent_again():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    rejected = anthropic.BadRequestError("too long", response=httpx.Response(400, request=request), body=None)

    class Rejected(_Stream):
        def stream(self, messages, config=None):
            raise rejected
            yield

        def invoke(self, messages, config=None):
            raise AssertionError("a rejected request was sent again")

    shown: list[str] = []
    reply = stream_structured_reply_with_fallback(Rejected([]), [], None, shown.append)
    assert reply == REPLY_FALLBACK
    assert shown == [REPLY_FALLBACK.intro_text]


def test_the_fallback_reply_is_used_when_every_attempt_fails():
    shown: list[str] = []
    reply = stream_structured_reply_with_fallback(_Stream([], fail_after=0), [], None, shown.append)
    assert reply == REPLY_FALLBACK
    assert shown == [REPLY_FALLBACK.intro_text]


# Figures and explainers


def _spec(layout: str, columns: list[tuple[str, str, str]], label_column: str = "", label_title: str = ""):
    return FigureSpec(
        layout=layout,
        label_column=label_column,
        label_title=label_title,
        columns=[FigureColumn(column=c, label=label, unit=unit) for c, label, unit in columns],
    )


def test_stats_copy_values_from_the_single_row():
    rows = [{"avg_sale_price": "4331780.836442786070", "transaction_count": 3216}]
    figures = build_figures(
        _spec("stats", [("avg_sale_price", "Average sale price", "aed"), ("transaction_count", "Sales", "count")]),
        rows,
        ["avg_sale_price", "transaction_count"],
    )
    assert figures == {
        "layout": "stats",
        "tiles": [
            {"label": "Average sale price", "value": "AED 4.33M"},
            {"label": "Sales", "value": "3,216"},
        ],
    }


def test_a_column_the_rows_do_not_have_is_dropped():
    rows = [{"sold_count": 7316}]
    spec = _spec("stats", [("sold_count", "Sales", "count"), ("avg_price", "Average price", "aed")])
    assert build_figures(spec, rows, ["sold_count"])["tiles"] == [{"label": "Sales", "value": "7,316"}]
    assert build_figures(_spec("stats", [("avg_price", "Average price", "aed")]), rows, ["sold_count"]) is None


def test_stats_need_exactly_one_row():
    rows = [{"n": 1}, {"n": 2}]
    assert build_figures(_spec("stats", [("n", "Count", "count")]), rows, ["n"]) is None


def test_a_table_names_each_row_and_caps_its_length():
    rows = [{"area_en": f"Area {i}", "avg_rent": 50000 + i, "yield_pct": "6.25"} for i in range(10)]
    table = build_figures(
        _spec("table", [("avg_rent", "Average rent", "aed"), ("yield_pct", "Yield", "percent")], "area_en", "Area"),
        rows,
        ["area_en", "avg_rent", "yield_pct"],
    )
    assert table["headers"] == ["Area", "Average rent", "Yield"]
    assert table["rows"][0] == ["Area 0", "AED 50,000", "6.25%"]
    assert len(table["rows"]) == 8 and table["hidden_rows"] == 2


def test_a_bar_chart_needs_numbers_and_row_names():
    rows = [{"year": 2023, "sales": "120"}, {"year": 2024, "sales": "180"}, {"year": 2025, "sales": None}]
    bar = build_figures(_spec("bar", [("sales", "Sales", "count")], "year"), rows, ["year", "sales"])
    assert bar["bars"] == [
        {"label": "2023", "value": 120.0, "display": "120"},
        {"label": "2024", "value": 180.0, "display": "180"},
    ]
    assert build_figures(_spec("bar", [("sales", "Sales", "count")]), rows, ["year", "sales"]) is None


@pytest.mark.parametrize(
    "value, unit, shown",
    [
        ("56103.7013", "aed", "AED 56,104"),
        (1250.4, "aed_per_sqft", "AED 1,250/sqft"),
        ("0.065", "fraction", "6.5%"),
        (2027, "year", "2027"),
        ("AED 79,000", "aed", "AED 79,000"),
        ("4.00", "number", "4"),
        ("986.684", "aed", "AED 986.68"),
    ],
)
def test_figures_read_the_way_a_buyer_reads_them(value, unit, shown):
    assert format_figure(value, unit) == shown


def test_only_one_block_is_shown_under_the_text():
    rows = [{"n": 5}]
    reply = StructuredReply(
        intro_text="x",
        figures=_spec("stats", [("n", "Count", "count")]),
        explainer=Explainer(kind="callout", title="Watch", points=["One thing"]),
    )
    blocks = build_reply_blocks(reply, rows, ["n"])
    assert blocks["figures"]["tiles"] == [{"label": "Count", "value": "5"}]
    assert blocks["explainer"] is None

    carded = reply.model_copy(update={"cards": [ReplyCard(title="JVC")]})
    assert build_reply_blocks(carded, rows, ["n"]) == {
        "cards": [ReplyCard(title="JVC").model_dump()],
        "figures": None,
        "explainer": None,
    }


def test_an_explainer_without_points_is_dropped():
    assert build_explainer(Explainer(kind="steps", title="How it works")) is None
    assert build_explainer(Explainer(kind="none", points=["a"])) is None
    shown = build_explainer(Explainer(kind="steps", title="Buying off-plan", points=["Reserve"], cautions=["x"]))
    assert shown == {"kind": "steps", "title": "Buying off-plan", "points": ["Reserve"], "cautions": []}


@pytest.mark.parametrize(
    "value, shown",
    [("8.9", "▲ 8.9%"), (-1.234, "▼ 1.2%"), ("0.01", "0%"), (13.16, "▲ 13.2%")],
)
def test_a_change_shows_its_direction(value, shown):
    assert format_figure(value, "change") == shown


def test_a_period_repeated_on_every_row_becomes_a_caption():
    rows = [
        {"bedrooms": "1-bed", "median": 1069300, "change": "9.9", "as_of": "May 2026", "yield": "6"},
        {"bedrooms": "2-bed", "median": 1550427, "change": "6.4", "as_of": "May 2026", "yield": "6"},
    ]
    spec = _spec(
        "table",
        [("median", "Median price", "aed"), ("change", "Yearly change", "change"), ("as_of", "As of", "text"), ("yield", "Yield", "percent")],
        "bedrooms",
        "Bedrooms",
    )
    table = build_figures(spec, rows, list(rows[0]))
    assert table["headers"] == ["Bedrooms", "Median price", "Yearly change", "Yield"]
    assert table["rows"][0] == ["1-bed", "AED 1.07M", "▲ 9.9%", "6%"]
    assert table["caption"] == ["As of: May 2026"]


def test_a_line_runs_oldest_first_and_skips_a_thin_series():
    rows = [
        {"month": "2026-03", "flats": "1300", "villas": "1900", "offices": None},
        {"month": "2026-02", "flats": "1290", "villas": None, "offices": "1100"},
        {"month": "2026-01", "flats": "1280", "villas": "1850", "offices": None},
    ]
    spec = _spec(
        "line",
        [("flats", "Apartments", "aed_per_sqft"), ("villas", "Villas", "aed_per_sqft"), ("offices", "Offices", "aed_per_sqft")],
        "month",
    )
    line = build_figures(spec, rows, list(rows[0]))
    assert line["labels"] == ["2026-01", "2026-02", "2026-03"]
    assert [series["name"] for series in line["series"]] == ["Apartments"]
    assert line["series"][0]["points"][-1] == {"value": 1300.0, "display": "AED 1,300/sqft"}
    assert build_figures(_spec("line", [("flats", "Apartments", "aed_per_sqft")]), rows, list(rows[0])) is None


def test_a_percent_column_named_as_a_change_shows_its_direction():
    rows = [{"market": "Villa prices", "yearly_change_pct": 13.16, "yield_pct": 5.1}, {"market": "Apartment prices", "yearly_change_pct": -0.4, "yield_pct": 6.2}]
    spec = _spec("table", [("yearly_change_pct", "Yearly change", "percent"), ("yield_pct", "Yield", "percent")], "market")
    assert build_figures(spec, rows, list(rows[0]))["rows"] == [["Villa prices", "▲ 13.2%", "5.1%"], ["Apartment prices", "▼ 0.4%", "6.2%"]]


def test_rows_with_two_dimensions_become_a_column_per_series():
    rows = [
        {"year": "2021", "layout": "1bed room+Hall", "median_rent": "58000"},
        {"year": "2021", "layout": "2 bed rooms+hall", "median_rent": "85000"},
        {"year": "2021", "layout": "Shop", "median_rent": "150000"},
        {"year": "2022", "layout": "1bed room+Hall", "median_rent": "62000"},
        {"year": "2022", "layout": "2 bed rooms+hall", "median_rent": "91000"},
        {"year": "2023", "layout": "1bed room+Hall", "median_rent": "70000"},
    ]
    spec = FigureSpec(
        layout="table",
        label_column="year",
        label_title="Year",
        columns=[FigureColumn(column="median_rent", label="Median rent", unit="aed")],
        series_column="layout",
        series=[FigureSeries(value="1bed room+Hall", label="1-bed"), FigureSeries(value="2 bed rooms+hall", label="2-bed")],
    )
    table = build_figures(spec, rows, list(rows[0]))
    assert table["headers"] == ["Year", "1-bed", "2-bed"]
    assert table["rows"] == [["2021", "AED 58,000", "AED 85,000"], ["2022", "AED 62,000", "AED 91,000"], ["2023", "AED 70,000", ""]]

    line = build_figures(spec.model_copy(update={"layout": "line"}), rows, list(rows[0]))
    assert [series["name"] for series in line["series"]] == ["1-bed"]


def test_one_data_column_is_never_shown_under_two_headers():
    rows = [{"year": "2021", "rent": "58000"}, {"year": "2022", "rent": "62000"}]
    spec = _spec("table", [("rent", "1-bed rent", "aed"), ("rent", "2-bed rent", "aed")], "year")
    assert build_figures(spec, rows, ["year", "rent"])["headers"] == ["Year", "1-bed rent"]


def test_a_long_run_of_periods_shows_the_latest():
    rows = [{"year": str(year), "sales": year} for year in range(2026, 2014, -1)]
    table = build_figures(_spec("table", [("sales", "Sales", "count")], "year"), rows, ["year", "sales"])
    assert [row[0] for row in table["rows"]] == [str(year) for year in range(2019, 2027)]
    assert table["hidden_rows"] == 4


def test_a_period_after_today_is_left_out():
    rows = [{"year": "2024", "rent": 1}, {"year": "2025", "rent": 2}, {"year": "2026", "rent": 3}, {"year": "2999", "rent": 9}]
    table = build_figures(_spec("table", [("rent", "Rent", "aed")], "year"), rows, ["year", "rent"])
    assert [row[0] for row in table["rows"]] == ["2024", "2025", "2026"]
