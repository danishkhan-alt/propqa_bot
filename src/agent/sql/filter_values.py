"""Check the values a drafted statement filters on, before it runs.

A filter such as `area_name_en = 'Al Mamzer'` or `property_sub_type_en = '2 Bedrooms'`
returns nothing, and an empty result reads as "there is no such data". Two checks run on
every `column = 'text'` and `column IN ('text', ...)`:

- The user's own spelling of a name that grounding matched to a stored value is swapped
  for that value in code: 'Al Mamzer' becomes 'Al Mamzar'. No model call.
- A filter on a column of people's names (`person_name: true` in the catalog) keeps only
  names the user typed. Any other pattern, such as '%singh%' for "a Hindi-speaking agent",
  guesses a person's language or background from their name, so it is removed.
- A window measured from today (CURRENT_DATE, NOW()) over a table whose data ends before
  today is reported with the date the data ends, since "the last week" of it is empty.
- A value outside a column's measured value list is reported, with the values it does
  hold. The statement still runs: large tables are profiled from a sample, so a rare value
  can be real. The report only explains a result that came back empty, so the retry can
  pick a stored value. A value that differs only in case is corrected in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import sqlglot
from sqlglot import exp

from agent.grounding.name_matching import is_typo_of, normalize_name
from agent.schemas.grounding import Grounding
from catalog import list_domains, load_column_profiles, load_domain
from common.services.app_clock import AppClock

# How many stored values a rejection lists, so the retry prompt stays short.
MAX_LISTED_VALUES = 25
_MISSING_COLUMN = re.compile(r'column "?([\w.]+)"? does not exist', re.IGNORECASE)


@dataclass(frozen=True)
class CheckedFilters:
    sql: str
    # "table.column: 'typed' -> 'stored'", for the log.
    corrections: list[str] = field(default_factory=list)
    # Person-name conditions removed because they used no name the user typed, for the log.
    removed: list[str] = field(default_factory=list)
    # Values outside a column's measured list: the likely reason when nothing comes back.
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _TableFacts:
    columns: frozenset[str]
    person_columns: frozenset[str]
    # Column to its complete stored value list, only for columns measured as a closed set.
    values: dict[str, tuple[str, ...]]
    # Date column to the last date it holds almost all rows up to, as "YYYY-MM-DD".
    covers_until: dict[str, str] = field(default_factory=dict)


def check_filter_values(sql: str, grounding: Grounding | None, typed_names: list[str] = ()) -> CheckedFilters:
    """`typed_names` are the names the user wrote this turn, as the router found them."""
    try:
        statement = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return CheckedFilters(sql=sql)
    if statement is None:
        return CheckedFilters(sql=sql)
    removed = _remove_guessed_person_filters(statement, typed_names)
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
    problems.extend(_windows_from_today_past_the_data(statement))
    if not corrections and not removed:
        return CheckedFilters(sql=sql, problems=problems)
    return CheckedFilters(
        sql=statement.sql(dialect="postgres"), corrections=corrections, removed=removed, problems=problems
    )


def _windows_from_today_past_the_data(statement: exp.Expression) -> list[str]:
    """Each date column, in a table the statement reads, whose data ends before a today-based window."""
    if not any(True for _ in statement.find_all(exp.CurrentDate, exp.CurrentTimestamp)):
        if not any(node.name.lower() == "now" for node in statement.find_all(exp.Anonymous)):
            return []
    today = AppClock.now().date().isoformat()
    facts = _catalog_facts()
    problems: list[str] = []
    for table in sorted(_statement_tables(statement)):
        for column, until in sorted((facts.get(table) or _NO_FACTS).covers_until.items()):
            if until < today:
                problems.append(
                    f"{table}.{column} holds data only up to {until}, so a window counted back from today "
                    f"finds nothing. For 'recent' or 'the last N days, weeks, or months', end the window at "
                    f"{until}. A named period such as 'this month' stays as asked."
                )
    return problems


def _remove_guessed_person_filters(statement: exp.Expression, typed_names: list[str]) -> list[str]:
    """Replace each condition on a person-name column that names nobody the user typed with TRUE."""
    typed = [set(normalize_name(name).split()) for name in typed_names]
    removed: list[str] = []
    for node in list(statement.find_all(exp.EQ, exp.In, exp.Like, exp.ILike)):
        column = node.this
        if not isinstance(column, exp.Column):
            continue
        table = _table_of(column)
        facts = _catalog_facts().get(table) if table else None
        if facts is None or column.name.lower() not in facts.person_columns:
            continue
        literals = [node.expression] if not isinstance(node, exp.In) else node.expressions
        texts = [item.this for item in literals if isinstance(item, exp.Literal) and item.is_string]
        if texts and all(any(set(normalize_name(text).split()) <= words for words in typed) for text in texts):
            continue
        removed.append(node.sql(dialect="postgres"))
        node.replace(exp.true())
    return removed


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


def _covers_end(covers: object) -> str:
    """The end of a measured "YYYY-MM-DD to YYYY-MM-DD" span, or "" when there is none."""
    parts = str(covers or "").split(" to ")
    if len(parts) != 2:
        return ""
    try:
        return date.fromisoformat(parts[1].strip()).isoformat()
    except ValueError:
        return ""


_NO_FACTS = _TableFacts(columns=frozenset(), person_columns=frozenset(), values={})


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
                person_columns=frozenset(
                    str(column.get("name") or "").lower()
                    for column in table.get("columns") or []
                    if column.get("person_name")
                ),
                values={
                    str(column).lower(): tuple(str(value) for value in column_facts["values"])
                    for column, column_facts in measured.items()
                    if isinstance(column_facts, dict) and column_facts.get("values")
                },
                covers_until={
                    str(column).lower(): until
                    for column, column_facts in measured.items()
                    if isinstance(column_facts, dict) and (until := _covers_end(column_facts.get("covers")))
                },
            )
            facts[qualified] = table_facts
            bare_names.setdefault(qualified.rsplit(".", 1)[-1], set()).add(qualified)
    # A bare name is only safe when one schema uses it.
    for bare, qualified_names in bare_names.items():
        if len(qualified_names) == 1 and bare not in facts:
            facts[bare] = facts[next(iter(qualified_names))]
    return facts


def exclude_rows_outside_region(sql: str, outside: dict[str, tuple[str, frozenset[int]]]) -> str:
    """Leave out the rows of region-scoped tables that lie outside the product's region.

    Added only to the statement that runs, so the conditions shown to the reply stay the user's.
    """
    if not outside:
        return sql
    try:
        statement = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return sql
    if statement is None:
        return sql
    changed = False
    for table in list(statement.find_all(exp.Table)):
        scoped = outside.get(_table_key(table))
        select = table.find_ancestor(exp.Select)
        if scoped is None or select is None or not scoped[1]:
            continue
        id_column, ids = scoped
        ids_sql = ", ".join(str(row_id) for row_id in sorted(ids))
        condition = sqlglot.parse_one(f"{table.alias_or_name}.{id_column} NOT IN ({ids_sql})", read="postgres")
        select.where(condition, append=True, copy=False)
        changed = True
    return statement.sql(dialect="postgres") if changed else sql
