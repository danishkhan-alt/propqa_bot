"""Turn a model draft into one capped SELECT over the loaded catalog."""

from __future__ import annotations

import re
from functools import lru_cache

import sqlglot
from sqlglot import exp

from agent.grounding.stored_values import PLACE_KIND_ORDER
from agent.schemas.sql import SegmentRule
from agent.sql.filter_values import _catalog_facts
from agent.sql.listing_sql_fragments import LISTINGS_TABLE
from catalog import list_domains, load_domain, load_domains

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
            if not _scoped_to_one_place(statement):
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


_ONE_FIGURE = re.compile(r"\b(?:average|mean|median|typical)\b", re.IGNORECASE)
_KIND_SPLIT = re.compile(
    r"\b(?:by|per|for each|split by|broken down by)\s+(?:\w+\s+){0,2}"
    r"(?:type|types|subtype|sub-type|bedroom|bedrooms|bed|beds|room|rooms|layout)s?\b",
    re.IGNORECASE,
)


def wants_one_overall_figure(message: str) -> bool:
    """One average or median for a place or a period, not a split by kind of property."""
    return bool(_ONE_FIGURE.search(message or "")) and not bool(_KIND_SPLIT.search(message or ""))


def overall_figure_sql(sql: str, message: str, rules: dict[str, SegmentRule]) -> str:
    """Turn a property-kind breakdown into the one figure the user asked for.

    A grouped median by flat, villa, or bedrooms answers a different question from
    "the average in this place". Place and time groupings are left as written.
    """
    if not wants_one_overall_figure(message):
        return sql
    try:
        statement = sqlglot.parse_one(sql or "", read="postgres")
    except sqlglot.errors.ParseError:
        return sql
    if not isinstance(statement, exp.Query):
        return sql
    segments = _segment_names(rules)
    for select in statement.find_all(exp.Select):
        group = select.args.get("group")
        if group is None:
            _use_asked_aggregate(select, message)
            continue
        keys = [column.name.lower() for key in group.expressions for column in key.find_all(exp.Column)]
        if not keys or not set(keys) <= segments:
            continue
        select.set("group", None)
        select.set("having", None)
        select.set("order", None)
        kept = [projection for projection in select.expressions if not _is_segment_label(projection, segments)]
        if kept:
            select.set("expressions", kept)
        _use_asked_aggregate(select, message)
    return statement.sql(dialect="postgres")


def _segment_names(rules: dict[str, SegmentRule]) -> set[str]:
    names: set[str] = set()
    for rule in rules.values():
        names.update(rule.segments)
    return names


def _is_segment_label(projection: exp.Expression, segments: set[str]) -> bool:
    if projection.find(exp.AggFunc) or projection.find(exp.WithinGroup):
        return False
    columns = list(projection.find_all(exp.Column))
    return bool(columns) and all(column.name.lower() in segments for column in columns)


def _use_asked_aggregate(select: exp.Select, message: str) -> None:
    """AVG when they asked for an average. A median stays only when they asked for one."""
    if re.search(r"\b(?:median|typical)\b", message, re.IGNORECASE) and not re.search(
        r"\b(?:average|mean)\b", message, re.IGNORECASE
    ):
        return
    for node in list(select.find_all(exp.WithinGroup, exp.Median)):
        column = next(iter(node.find_all(exp.Column)), None)
        if column is None:
            continue
        node.replace(exp.Avg(this=column.copy()))


def _scoped_to_one_place(statement: exp.Expression) -> bool:
    """True when a filter pins one stored place, so one average is the figure for that place."""
    places = _place_columns()
    if not places:
        return False
    for node in statement.find_all(exp.EQ, exp.In):
        column = node.this if isinstance(node.this, exp.Column) else None
        if column is None or column.name.lower() not in places:
            continue
        if isinstance(node, exp.EQ) and isinstance(node.expression, exp.Literal) and node.expression.is_string:
            return True
        if isinstance(node, exp.In) and any(isinstance(item, exp.Literal) and item.is_string for item in node.expressions):
            return True
    return False


@lru_cache(maxsize=1)
def _place_columns() -> frozenset[str]:
    found: set[str] = set()
    for listed in list_domains():
        for item in load_domain(str(listed["id"])).get("named_values") or []:
            if str(item.get("kind") or "") in PLACE_KIND_ORDER and item.get("column"):
                found.add(str(item["column"]).lower())
    return frozenset(found)


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
    _drop_unknown_output_columns(statement)
    constant = _condition_on_no_column(statement)
    if constant is not None:
        raise SqlRejected(
            f"The condition {constant} tests only fixed values, not a column, so it filters nothing. Test a "
            "column that holds what was asked; if no column holds it, leave sql empty and set missing."
        )
    if _has_unbracketed_or(statement):
        raise SqlRejected(
            "A WHERE mixes AND and OR without parentheses. AND binds first, so the other conditions "
            "do not apply to every OR branch. Put the OR alternatives in parentheses."
        )
    capped = _cap_rows(statement, row_cap)
    return capped.sql(dialect="postgres")


def _drop_unknown_output_columns(statement: exp.Expression) -> None:
    """Drop a selected column the table does not have, when the select still has another column.

    A coordinate the catalog does not list should not fail a lookup that already names the place.
    A statement whose every column is unknown is left for the database error, which lists the real ones.
    """
    facts = _catalog_facts()
    for select in statement.find_all(exp.Select):
        sources = _select_sources(select)
        kept: list[exp.Expression] = []
        dropped = False
        for projection in select.expressions:
            column = _bare_column(projection)
            if column is not None and _column_is_unknown(column, sources, facts):
                dropped = True
                continue
            kept.append(projection)
        if dropped and kept:
            select.set("expressions", kept)


def _bare_column(projection: exp.Expression) -> exp.Column | None:
    if isinstance(projection, exp.Column):
        return projection
    if isinstance(projection, exp.Alias) and isinstance(projection.this, exp.Column):
        return projection.this
    return None


def _column_is_unknown(column: exp.Column, sources: dict[str, str], facts: dict) -> bool:
    if column.table:
        table = sources.get(column.table.lower())
    elif len(sources) == 1:
        table = next(iter(sources.values()))
    else:
        return False
    if table is None:
        return False
    known = facts.get(table)
    if known is None:
        bare = table.rsplit(".", 1)[-1]
        known = facts.get(bare)
    if known is None or not known.columns:
        return False
    return column.name.lower() not in known.columns


def _select_sources(select: exp.Select) -> dict[str, str]:
    tables: list[exp.Expression] = []
    source = select.args.get("from") or select.args.get("from_")
    if source is not None:
        tables.append(source.this)
    tables.extend(join.this for join in select.args.get("joins") or [])
    sources: dict[str, str] = {}
    for table in tables:
        if isinstance(table, exp.Table) and table.name:
            key = f"{table.db.lower()}.{table.name.lower()}" if table.db else table.name.lower()
            sources[table.alias_or_name.lower()] = key
    return sources


_COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.ILike, exp.In, exp.Is)


def _condition_on_no_column(statement: exp.Expression) -> str | None:
    """A WHERE or HAVING comparison with no column, aggregate, or subquery in it, such as LOWER('Villa') LIKE '%villa%'."""
    for clause in [*statement.find_all(exp.Where), *statement.find_all(exp.Having)]:
        for node in clause.find_all(*_COMPARISONS):
            if node.find(exp.Column) is None and node.find(exp.Select) is None and node.find(exp.AggFunc) is None:
                return node.sql(dialect="postgres")
    return None


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
