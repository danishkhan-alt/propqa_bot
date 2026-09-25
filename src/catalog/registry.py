from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_DIR = Path(__file__).resolve().parent
DOMAINS_DIR = CATALOG_DIR / "domains"
PROFILES_DIR = CATALOG_DIR / "profiles"
INDEX_PATH = DOMAINS_DIR / "index.yaml"
NAME_ALIASES_PATH = CATALOG_DIR / "name_aliases.yaml"
RECIPES_PATH = CATALOG_DIR / "recipes.yaml"

# Keys the grounding code reads. The SQL model never sees them.
_GROUNDING_KEYS = ("named_values",)
# A column this full or fuller is shown without a fill rate.
_FULL_ENOUGH = 0.95


def list_domains() -> list[dict]:
    """Compact domain index for the query / domain routers."""
    return list(_read_yaml(INDEX_PATH).get("domains") or [])


def load_domain(domain_id: str) -> dict:
    """Full SQL-agent catalog for one domain."""
    path = DOMAINS_DIR / f"{domain_id}.yaml"
    if not path.exists():
        known = ", ".join(d["id"] for d in list_domains())
        raise KeyError(f"Unknown domain '{domain_id}'. Known: {known}")
    return _read_yaml(path)


def load_domains(domain_ids: list[str]) -> list[dict]:
    return [load_domain(domain_id) for domain_id in domain_ids]


def load_column_profiles(domain_id: str) -> dict:
    """Measured fill rate and values per column, written by `python -m catalog.profiler`."""
    path = PROFILES_DIR / f"{domain_id}.yaml"
    if not path.exists():
        return {}
    return _read_yaml(path)


def domain_prompt(domain: dict) -> str:
    """YAML fragment the SQL agent can be given as schema context, with measured column facts."""
    visible = {key: value for key, value in domain.items() if key not in _GROUNDING_KEYS}
    profiles = load_column_profiles(str(domain.get("id") or ""))
    if profiles:
        visible["tables"] = [_with_profile(table, profiles) for table in visible.get("tables") or []]
    return yaml.safe_dump(visible, sort_keys=False, allow_unicode=True, width=100)


def load_prompt(domain_ids: list[str]) -> str:
    parts = [domain_prompt(load_domain(domain_id)) for domain_id in domain_ids]
    return "\n---\n".join(parts)


def date_coverage(tables: set[str] | list[str]) -> list[dict]:
    """Measured date spans of the given tables, as {table, column, covers}."""
    index = _coverage_index()
    return [dict(span) for name in sorted({str(t).lower() for t in tables}) for span in index.get(name, ())]


@lru_cache(maxsize=1)
def _coverage_index() -> dict[str, tuple[dict, ...]]:
    index: dict[str, tuple[dict, ...]] = {}
    for domain in list_domains():
        profiles = load_column_profiles(domain["id"])
        for table in load_domain(domain["id"]).get("tables") or []:
            qualified = str(table.get("qualified_name") or "")
            measured = profiles.get(qualified) or {}
            spans = tuple(
                {
                    "table": table.get("description") or qualified,
                    "column": column.get("meaning") or column.get("name"),
                    "covers": covers,
                }
                for column in table.get("columns") or []
                if (covers := (measured.get(column.get("name")) or {}).get("covers"))
            )
            if spans:
                index[qualified.lower()] = spans
    return index


def named_columns() -> list[dict]:
    """Every `named_values` declaration across the catalog."""
    declared: list[dict] = []
    for domain in list_domains():
        declared.extend(load_domain(domain["id"]).get("named_values") or [])
    return declared


def load_recipes() -> list[dict]:
    """Fixed lookups the domain router may pick instead of a drafted statement."""
    if not RECIPES_PATH.exists():
        return []
    return list(_read_yaml(RECIPES_PATH).get("recipes") or [])


def name_aliases() -> dict[str, list[str]]:
    if not NAME_ALIASES_PATH.exists():
        return {}
    payload = _read_yaml(NAME_ALIASES_PATH)
    return {str(wording): [str(name) for name in names or []] for wording, names in payload.items()}


def _read_yaml(path: Path) -> dict:
    """Catalog files are fixed for the life of a process. Each caller gets its own copy."""
    return copy.deepcopy(_parsed_yaml(path))


@lru_cache(maxsize=None)
def _parsed_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _with_profile(table: dict, profiles: dict) -> dict:
    measured = profiles.get(table.get("qualified_name") or table.get("name")) or {}
    if not measured:
        return table
    columns = []
    for column in table.get("columns") or []:
        facts = measured.get(column.get("name")) or {}
        shown = dict(column)
        filled = facts.get("filled")
        if filled is not None and filled < _FULL_ENOUGH:
            shown["filled"] = f"{filled:.0%}"
        for listed in ("values", "common_values"):
            if facts.get(listed):
                shown.pop("examples", None)
                shown[listed] = facts[listed]
        if facts.get("covers"):
            shown["covers"] = facts["covers"]
        columns.append(shown)
    return {**table, "columns": columns}
