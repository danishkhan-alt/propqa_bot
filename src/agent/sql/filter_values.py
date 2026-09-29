"""Check the values a drafted statement filters on, before it runs.

A filter such as `area_name_en = 'Al Mamzer'` or `property_sub_type_en = '2 Bedrooms'`
returns nothing, and an empty result reads as "there is no such data". Two checks run on
every `column = 'text'` and `column IN ('text', ...)`:

- The user's own spelling of a name that grounding matched to a stored value is swapped
  for that value in code: 'Al Mamzer' becomes 'Al Mamzar'. No model call.
- A value outside a column's measured value list is reported, with the values it does
  hold. The statement still runs: large tables are profiled from a sample, so a rare value
  can be real. The report only explains a result that came back empty, so the retry can
  pick a stored value. A value that differs only in case is corrected in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import sqlglot
from sqlglot import exp

from agent.grounding.name_matching import is_typo_of, normalize_name
from agent.schemas.grounding import Grounding
from catalog import list_domains, load_column_profiles, load_domain

# How many stored values a rejection lists, so the retry prompt stays short.
MAX_LISTED_VALUES = 25
_MISSING_COLUMN = re.compile(r'column "?([\w.]+)"? does not exist', re.IGNORECASE)


@dataclass(frozen=True)
class CheckedFilters:
    sql: str
    # "table.column: 'typed' -> 'stored'", for the log.
    corrections: list[str] = field(default_factory=list)
    # Values outside a column's measured list: the likely reason when nothing comes back.
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _TableFacts:
    columns: frozenset[str]
    # Column to its complete stored value list, only for columns measured as a closed set.
    values: dict[str, tuple[str, ...]]


def check_filter_values(sql: str, grounding: Grounding | None) -> CheckedFilters:
    try:
        statement = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return CheckedFilters(sql=sql)
    if statement is None:
        return CheckedFilters(sql=sql)
    grounded = _grounded_values_by_column(grounding)
    corrections: list[str] = []
    problems: list[str] = []
    for column, literals in _filtered_literals(statement):
        table = _table_of(column)
        if table is None:
            continue
        facts = _catalog_facts().get(table)
        name = column.name.lower()
        for literal in literals:
            typed = literal.this
            stored = _stored_spelling(typed, grounded.get((table, name), []))
            if stored is None and facts is not None and name in facts.values:
                stored = _closed_set_spelling(typed, facts.values[name])
                if stored is None:
                    listed = ", ".join(f"'{value}'" for value in facts.values[name][:MAX_LISTED_VALUES])
                    problems.append(f"{table}.{name} does not hold '{typed}'. Its values are: {listed}.")
                    continue
            if stored is not None and stored != typed:
                literal.replace(exp.Literal.string(stored))
                corrections.append(f"{table}.{name}: '{typed}' -> '{stored}'")
    if not corrections:
        return CheckedFilters(sql=sql, problems=problems)
    return CheckedFilters(sql=statement.sql(dialect="postgres"), corrections=corrections, problems=problems)


def explain_missing_column(error: str, sql: str) -> str:
    """The database's "column does not exist", with the columns the statement's tables do have."""
    if not _MISSING_COLUMN.search(error or ""):
        return error
    try:
        statement = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return error
    facts = _catalog_facts()
    listed = [
        f"{table} has: {', '.join(sorted(facts[table].columns))}."
        for table in sorted(_statement_tables(statement))
        if table in facts
    ]
    return " ".join([error, "Use only these columns.", *listed]) if listed else error


def _filtered_literals(statement: exp.Expression) -> list[tuple[exp.Column, list[exp.Literal]]]:
    """Each `column = 'text'` and `column IN ('text', ...)`, with its string literals."""
    found: list[tuple[exp.Column, list[exp.Literal]]] = []
    for node in statement.find_all(exp.EQ, exp.In):
        if isinstance(node, exp.EQ):
            left, right = node.this, node.expression
            if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
                left, right = right, left
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
                found.append((left, [right]))
        elif isinstance(node.this, exp.Column) and not node.args.get("query"):
            literals = [item for item in node.expressions if isinstance(item, exp.Literal) and item.is_string]
            if literals:
                found.append((node.this, literals))
    return found


def _table_of(column: exp.Column) -> str | None:
    """The catalog table a column belongs to, from its qualifier or its SELECT's only fitting source."""
    select = column.find_ancestor(exp.Select)
    if select is None:
        return None
    sources = _sources(select)
    if column.table:
        return sources.get(column.table.lower())
    facts = _catalog_facts()
    fitting = {table for table in sources.values() if column.name.lower() in facts.get(table, _NO_FACTS).columns}
    return fitting.pop() if len(fitting) == 1 else None


def _sources(select: exp.Select) -> dict[str, str]:
    tables: list[exp.Expression] = []
    source = select.args.get("from") or select.args.get("from_")
    if source is not None:
        tables.append(source.this)
    tables.extend(join.this for join in select.args.get("joins") or [])
    sources: dict[str, str] = {}
    for table in tables:
        if isinstance(table, exp.Table) and table.name:
            sources[table.alias_or_name.lower()] = _table_key(table)
    return sources


def _statement_tables(statement: exp.Expression) -> set[str]:
    return {_table_key(table) for table in statement.find_all(exp.Table) if table.name}


def _table_key(table: exp.Table) -> str:
    return f"{table.db.lower()}.{table.name.lower()}" if table.db else table.name.lower()


def _grounded_values_by_column(grounding: Grounding | None) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """(table, column) to (typed name, stored value) for every stored match, under both table names."""
    by_column: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for name in grounding.names if grounding is not None else []:
        for match in name.stored:
            table, column = match.table.lower(), match.column.lower()
            for key in {(table, column), (table.rsplit(".", 1)[-1], column)}:
                by_column.setdefault(key, []).append((name.text, match.value))
    return by_column


def _stored_spelling(typed: str, grounded: list[tuple[str, str]]) -> str | None:
    """The stored value a literal means when it is the user's own spelling of a grounded name."""
    if not grounded:
        return None
    wanted = normalize_name(typed)
    for _, value in grounded:
        if value == typed:
            return typed
    for _, value in grounded:
        if normalize_name(value) == wanted:
            return value
    meant = [value for text, value in grounded if normalize_name(text) == wanted or is_typo_of(typed, text)]
    return meant[0] if len(set(meant)) == 1 else None


def _closed_set_spelling(typed: str, values: tuple[str, ...]) -> str | None:
    if typed in values:
        return typed
    folded = [value for value in values if value.casefold() == typed.casefold()]
    return folded[0] if len(folded) == 1 else None


_NO_FACTS = _TableFacts(columns=frozenset(), values={})


@lru_cache(maxsize=1)
def _catalog_facts() -> dict[str, _TableFacts]:
    """Every catalog table, under its qualified and bare name, with its columns and closed value lists."""
    facts: dict[str, _TableFacts] = {}
    bare_names: dict[str, set[str]] = {}
    for listed in list_domains():
        domain = load_domain(listed["id"])
        profiles = load_column_profiles(listed["id"])
        schema = str(domain.get("schema") or "").strip().lower()
        for table in domain.get("tables") or []:
            name = str(table.get("name") or "").strip().lower()
            qualified = str(table.get("qualified_name") or (f"{schema}.{name}" if schema else name)).strip().lower()
            measured = profiles.get(table.get("qualified_name") or "") or profiles.get(qualified) or {}
            table_facts = _TableFacts(
                columns=frozenset(str(column.get("name") or "").lower() for column in table.get("columns") or []),
                values={
                    str(column).lower(): tuple(str(value) for value in column_facts["values"])
                    for column, column_facts in measured.items()
                    if isinstance(column_facts, dict) and column_facts.get("values")
                },
            )
            facts[qualified] = table_facts
            bare_names.setdefault(qualified.rsplit(".", 1)[-1], set()).add(qualified)
    # A bare name is only safe when one schema uses it.
    for bare, qualified_names in bare_names.items():
        if len(qualified_names) == 1 and bare not in facts:
            facts[bare] = facts[next(iter(qualified_names))]
    return facts
