"""What the SQL model is shown of the catalog."""

from __future__ import annotations

import yaml

from catalog import (
    get_table_date_coverage,
    list_domains,
    load_domain,
    load_named_value_declarations,
    render_domain_prompt,
)


def _columns(prompt: str, table: str) -> dict[str, dict]:
    tables = yaml.safe_load(prompt)["tables"]
    chosen = next(item for item in tables if item["qualified_name"] == table)
    return {column["name"]: column for column in chosen["columns"]}


def test_the_sql_model_sees_measured_facts_and_not_grounding_declarations():
    prompt = render_domain_prompt(load_domain("listings"))
    assert "named_values" not in prompt
    columns = _columns(prompt, "public.properties")
    assert columns["price_min"]["filled"] == "0%"
    assert "filled" not in columns["price_max"]
    assert columns["purpose"]["values"] == ["for_sale", "for_rent"]


def test_every_named_column_is_a_catalog_column():
    columns_by_table = {
        table["qualified_name"]: {column["name"] for column in table["columns"]}
        for domain in list_domains()
        for table in load_domain(domain["id"]).get("tables") or []
        if table.get("qualified_name")
    }
    for declared in load_named_value_declarations():
        columns = columns_by_table[declared["table"]]
        assert declared["column"] in columns, declared
        if declared.get("same_place_as"):
            assert declared["same_place_as"] in columns, declared


def test_a_loaded_domain_is_a_copy_the_caller_may_change():
    first = load_domain("listings")
    first["tables"].clear()
    assert load_domain("listings")["tables"]


def test_the_sql_model_sees_how_far_a_date_column_reaches():
    prompt = render_domain_prompt(load_domain("transactions"))
    columns = _columns(prompt, "chatbot_ai.rent_contracts")
    first, _, last = columns["contract_start_date"]["covers"].partition(" to ")
    assert first < last


def test_date_coverage_names_the_data_not_the_table():
    spans = get_table_date_coverage({"CHATBOT_AI.rent_contracts"})
    assert spans
    assert all("rent_contracts" not in span["table"] for span in spans)
    assert get_table_date_coverage({"no.such_table"}) == []
