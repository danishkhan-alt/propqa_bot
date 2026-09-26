"""Turn a model draft into one capped SELECT over the loaded catalog."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from agent.schemas.sql import SegmentRule
from agent.sql.listing_sql_fragments import LISTINGS_TABLE
from catalog import load_domains

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class SqlRejected(Exception):
    """The statement is not a single read over the loaded tables."""


def tables_in_domains(domain_ids: list[str]) -> set[str]:
    """Bare and schema-qualified names the loaded packs are allowed to touch."""
    allowed: set[str] = set()
    for domain in load_domains(domain_ids):
        schema = str(domain.get("schema") or "").strip().lower()
        for table in domain.get("tables") or []:
            name = str(table.get("name") or "").strip().lower()
            qualified = str(table.get("qualified_name") or "").strip().lower()
            table_schema = schema
            if "." in qualified:
                table_schema, qualified_name = qualified.split(".", 1)
                name = qualified_name or name
                allowed.add(qualified)
            if not name:
                continue
            allowed.add(name)
            if table_schema:
                allowed.add(f"{table_schema}.{name}")
    return allowed


def segment_rules(domain_ids: list[str]) -> dict[str, SegmentRule]:
    """Rules for every loaded table that declares segments, by bare and qualified name."""
    rules: dict[str, SegmentRule] = {}
    for domain in load_domains(domain_ids):
        for table in domain.get("tables") or []:
            segments = tuple(str(name).lower() for name in table.get("segments") or [])
            basis = tuple(str(name).lower() for name in table.get("basis") or [])
            if not segments and not basis:
                continue
            qualified = str(
                table.get("qualified_name") or table.get("name") or ""
            ).lower()
            rule = SegmentRule(
                table=qualified,
                columns=frozenset(
                    str(column.get("name") or "").lower()
                    for column in table.get("columns") or []
                ),
                segments=segments,
                basis=basis,
            )
            rules[qualified] = rule
            rules[qualified.rsplit(".", 1)[-1]] = rule
    return rules


def blended_average_reasons(sql: str, rules: dict[str, SegmentRule]) -> list[str]:
    """Why an average in `sql` mixes kinds of property, one reason per table. Empty when it does not.

    An average (AVG, MEDIAN, PERCENTILE) over a declared table must split by a segment and
    pin every basis column, either in a filter or in a grouping. A grouping reached through
    a CTE or subquery alias counts. Presence checks such as IS NOT NULL do not.
    """
    if not rules:
        return []
    try:
        statement = sqlglot.parse_one(sql or "", read="postgres")
    except sqlglot.errors.ParseError:
        return []
    if statement is None:
        return []
    averaged = _averaged_columns(statement)
    if not averaged:
        return []
    split = _filtered_or_grouped_columns(statement)
    reasons: list[str] = []
    seen: set[str] = set()
    for name in sorted(_tables_in_statement(statement)):
        rule = rules.get(name) or rules.get(name.rsplit(".", 1)[-1])
        if rule is None or rule.table in seen or not (averaged & rule.columns):
            continue
        seen.add(rule.table)
        if rule.segments and not split.intersection(rule.segments):
            reasons.append(
                f"The average over {rule.table} mixes kinds of property. Group by one of "
                f"{', '.join(rule.segments)} (or filter to the one the user named), with a count per group."
            )
        missing = [column for column in rule.basis if column not in split]
        if missing:
            reasons.append(
                f"The average over {rule.table} mixes different measures. Filter or group by {', '.join(missing)}."
            )
    return reasons


_AVERAGES = (exp.Avg, exp.Median)
_PERCENTILES = (exp.PercentileCont, exp.PercentileDisc)


def _averaged_columns(statement: exp.Expression) -> set[str]:
    names: set[str] = set()
    for node in statement.find_all(*_AVERAGES, exp.WithinGroup, *_PERCENTILES):
        if isinstance(node, exp.WithinGroup) and not isinstance(
            node.this, _PERCENTILES
        ):
            continue
        names.update(column.name.lower() for column in node.find_all(exp.Column))
    return names


def _filtered_or_grouped_columns(statement: exp.Expression) -> set[str]:
    """Column names that filter or group rows, following aliases out of CTEs and subqueries."""
    split: set[str] = set()
    for clause in [*statement.find_all(exp.Where), *statement.find_all(exp.Having)]:
        for term in (
            clause.this.flatten() if isinstance(clause.this, exp.And) else [clause.this]
        ):
            if not _is_join_or_not_null_check(term):
                split.update(
                    column.name.lower() for column in term.find_all(exp.Column)
                )
    grouped: set[str] = set()
    for select in statement.find_all(exp.Select):
        projections = select.expressions
        by_alias = {
            projection.alias.lower(): projection
            for projection in projections
            if projection.alias
        }
        group = select.args.get("group")
        keys = list(group.expressions) if group is not None else []
        for key in keys:
            if (
                isinstance(key, exp.Literal)
                and key.is_int
                and 0 < int(key.this) <= len(projections)
            ):
                key = projections[int(key.this) - 1]
            elif (
                isinstance(key, exp.Column)
                and not key.table
                and key.name.lower() in by_alias
            ):
                key = by_alias[key.name.lower()]
            grouped.update(column.name.lower() for column in key.find_all(exp.Column))
    for window in statement.find_all(exp.Window):
        for key in window.args.get("partition_by") or []:
            grouped.update(column.name.lower() for column in key.find_all(exp.Column))
    # A grouped alias stands for the columns it was built from, in whichever scope named it.
    aliases = [
        (alias.alias.lower(), alias)
        for alias in statement.find_all(exp.Alias)
        if alias.alias
    ]
    changed = True
    while changed:
        changed = False
        for name, alias in aliases:
            if name in grouped:
                inner = {
                    column.name.lower() for column in alias.this.find_all(exp.Column)
                }
                if not inner <= grouped:
                    grouped |= inner
                    changed = True
    return split | grouped


def prepare_select(sql: str, allowed_tables: set[str], row_cap: int) -> str:
    """Parse, reject anything except one catalog SELECT, and cap the row count."""
    text = (sql or "").strip()
    if not text:
        raise SqlRejected("SQL was empty")
    try:
        parsed = sqlglot.parse(text, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise SqlRejected(_parse_reason(exc)) from exc
    statements = [statement for statement in parsed if statement is not None]
    if len(statements) != 1:
        raise SqlRejected("Only one statement is allowed")
    statement = statements[0]
    if not isinstance(statement, exp.Query) or statement.find(exp.Into):
        raise SqlRejected("Only SELECT is allowed")
    referenced = _tables_in_statement(statement)
    if not referenced:
        raise SqlRejected("Query does not use a catalog table")
    unknown = sorted(name for name in referenced if name not in allowed_tables)
    if unknown:
        raise SqlRejected("Query uses tables outside the loaded catalog")
    if _has_unbracketed_or(statement):
        raise SqlRejected(
            "A WHERE mixes AND and OR without parentheses. AND binds first, so the other conditions "
            "do not apply to every OR branch. Put the OR alternatives in parentheses."
        )
    capped = _cap_rows(statement, row_cap)
    return capped.sql(dialect="postgres")


def _has_unbracketed_or(statement: exp.Expression) -> bool:
    """An OR with an unparenthesized AND beneath it: `a AND b OR c` reads as `(a AND b) OR c`.

    Written that way it is nearly always a slip that drops a filter from one branch. sqlglot
    keeps explicit parentheses as Paren nodes, so a bracketed grouping is not flagged.
    """
    for clause in [*statement.find_all(exp.Where), *statement.find_all(exp.Having)]:
        for node in clause.find_all(exp.Or):
            if isinstance(node.this, exp.And) or isinstance(node.expression, exp.And):
                return True
    return False


def applied_conditions(sql: str) -> list[str]:
    """Every WHERE and HAVING condition in a statement, one per AND term, in order.

    These are what narrowed the rows, so the reply can name them instead of guessing.
    Join equalities between two columns and IS NOT NULL checks are left out.
    """
    try:
        statement = sqlglot.parse_one(sql or "", read="postgres")
    except sqlglot.errors.ParseError:
        return []
    if statement is None:
        return []
    conditions: list[str] = []
    for clause in [*statement.find_all(exp.Where), *statement.find_all(exp.Having)]:
        # An aggregate's FILTER (WHERE ...) picks rows for one figure; it narrows no result.
        if isinstance(clause.parent, exp.Filter):
            continue
        for term in (
            clause.this.flatten() if isinstance(clause.this, exp.And) else [clause.this]
        ):
            if _is_join_or_not_null_check(term):
                continue
            text = term.sql(dialect="postgres")
            if text not in conditions:
                conditions.append(text)
    return conditions


def referenced_tables(sql: str) -> set[str]:
    try:
        statement = sqlglot.parse_one(sql or "", read="postgres")
    except sqlglot.errors.ParseError:
        return set()
    return _tables_in_statement(statement) if statement is not None else set()


def live_listing_id_column(sql: str) -> str | None:
    """The result column holding the live listing id, when each row is one live listing.

    Only a top-level SELECT that projects the id of public.properties counts. DLD tables
    also have a property_id column, but it is not a listing id, so names alone do not tell.
    """
    try:
        statement = sqlglot.parse_one(sql or "", read="postgres")
    except sqlglot.errors.ParseError:
        return None
    if not isinstance(statement, exp.Select):
        return None
    sources = _direct_sources(statement)
    for projection in statement.expressions:
        column = projection.unalias()
        if not isinstance(column, exp.Column) or column.name.lower() != "id":
            continue
        qualifier = column.table.lower()
        if qualifier:
            table = sources.get(qualifier)
        else:
            table = next(iter(sources.values())) if len(sources) == 1 else None
        if table == LISTINGS_TABLE:
            return projection.alias_or_name
    return None


def _direct_sources(select: exp.Select) -> dict[str, str]:
    """Alias (or bare name) to full table name, for tables in this SELECT's FROM and JOINs."""
    tables: list[exp.Expression] = []
    source = select.args.get("from") or select.args.get("from_")
    if source is not None:
        tables.append(source.this)
    tables.extend(join.this for join in select.args.get("joins") or [])
    sources: dict[str, str] = {}
    for table in tables:
        if not isinstance(table, exp.Table) or not table.name:
            continue
        full = (
            f"{table.db.lower()}.{table.name.lower()}"
            if table.db
            else table.name.lower()
        )
        sources[table.alias_or_name.lower()] = full
    return sources


def _is_join_or_not_null_check(term: exp.Expression) -> bool:
    if (
        isinstance(term, exp.EQ)
        and isinstance(term.this, exp.Column)
        and isinstance(term.expression, exp.Column)
    ):
        return True
    # `a IS NOT NULL` parses as a negated Is; `NOT a IS NULL` as Not wrapping one.
    negated = isinstance(term, exp.Not)
    check = term.this if negated else term
    if not isinstance(check, exp.Is) or not isinstance(check.expression, exp.Null):
        return False
    return negated != bool(check.args.get("negate"))


def _tables_in_statement(statement: exp.Expression) -> set[str]:
    cte_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE) if cte.alias}
    referenced: set[str] = set()
    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if not name or (not table.db and name in cte_names):
            continue
        referenced.add(f"{table.db.lower()}.{name}" if table.db else name)
    return referenced


def _cap_rows(statement: exp.Expression, row_cap: int) -> exp.Expression:
    cap = row_cap + 1
    limit = statement.args.get("limit")
    if limit is not None:
        expression = limit.args.get("expression")
        if (
            isinstance(expression, exp.Literal)
            and expression.is_int
            and int(expression.this) <= cap
        ):
            return statement
    return statement.limit(cap)


def _parse_reason(exc: Exception) -> str:
    text = _ANSI.sub("", str(exc))
    line = text.splitlines()[0].strip() if text else ""
    return line[:200] or "SQL could not be parsed"
