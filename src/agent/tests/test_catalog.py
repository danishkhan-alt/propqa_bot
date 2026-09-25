"""What the SQL model is shown of the catalog."""

from __future__ import annotations

import yaml

from catalog import domain_prompt, list_domains, load_domain, named_columns


def _columns(prompt: str, table: str) -> dict[str, dict]:
    tables = yaml.safe_load(prompt)["tables"]
    chosen = next(item for item in tables if item["qualified_name"] == table)
    return {column["name"]: column for column in chosen["columns"]}


def test_the_sql_model_sees_measured_facts_and_not_grounding_declarations():
    prompt = domain_prompt(load_domain("listings"))
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
    for declared in named_columns():
        columns = columns_by_table[declared["table"]]
        assert declared["column"] in columns, declared
        if declared.get("same_place_as"):
            assert declared["same_place_as"] in columns, declared


def test_a_loaded_domain_is_a_copy_the_caller_may_change():
    first = load_domain("listings")
    first["tables"].clear()
    assert load_domain("listings")["tables"]
