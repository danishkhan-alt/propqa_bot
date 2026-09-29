"""Rows of a table that mixes emirates: which lie outside Dubai, and leaving them out of a lookup."""

from __future__ import annotations

from agent.enums.grounding import Breadth
from agent.grounding.region_rows import RegionScope, ids_outside_region
from agent.schemas.grounding_index import LocationNode
from agent.sql.filter_values import exclude_rows_outside_region

SCOPE = RegionScope("public.offplan_projects_new", "id", "locations_v2_id", "project_city")
NODES = [
    LocationNode(1, None, "UAE", Breadth.REGION),
    LocationNode(2, 1, "Dubai", Breadth.REGION),
    LocationNode(3, 1, "Abu Dhabi", Breadth.REGION),
    LocationNode(20, 2, "Jumeirah Village Circle (JVC)", Breadth.AREA),
    LocationNode(30, 3, "Yas Island", Breadth.AREA),
]


def test_a_row_follows_its_own_link_and_an_unlinked_row_follows_its_place_name():
    rows = [
        {"id": 1, "locations_v2_id": 20, "project_city": "JVC"},
        {"id": 2, "locations_v2_id": 30, "project_city": "Yas Island"},
        {"id": 3, "locations_v2_id": None, "project_city": "Yas Island"},
        {"id": 4, "locations_v2_id": None, "project_city": "JVC"},
        # No linked row explains this place name, so it is kept rather than dropped on a guess.
        {"id": 5, "locations_v2_id": None, "project_city": "Somewhere New"},
    ]
    assert ids_outside_region(rows, SCOPE, NODES, "Dubai") == frozenset({2, 3})


def test_rows_outside_the_region_are_left_out_of_the_statement_that_runs():
    outside = {"public.offplan_projects_new": ("id", frozenset({7, 3}))}
    sql = exclude_rows_outside_region(
        "SELECT o.project_name_en FROM public.offplan_projects_new AS o WHERE o.starting_price < 900000", outside
    )
    assert "o.starting_price < 900000" in sql
    assert "NOT o.id IN (3, 7)" in sql


def test_a_statement_without_a_scoped_table_is_unchanged():
    sql = "SELECT 1 FROM chatbot_ai.real_estate_transactions"
    assert exclude_rows_outside_region(sql, {"public.offplan_projects_new": ("id", frozenset({1}))}) == sql
