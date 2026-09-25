"""Turn a model draft into one capped SELECT over the loaded catalog."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

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
    referenced = _referenced_tables(statement)
    if not referenced:
        raise SqlRejected("Query does not use a catalog table")
    unknown = sorted(name for name in referenced if name not in allowed_tables)
    if unknown:
        raise SqlRejected("Query uses tables outside the loaded catalog")
    capped = _cap_rows(statement, row_cap)
    return capped.sql(dialect="postgres")


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
        for term in clause.this.flatten() if isinstance(clause.this, exp.And) else [clause.this]:
            if _is_join_or_presence(term):
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
    return _referenced_tables(statement) if statement is not None else set()


def _is_join_or_presence(term: exp.Expression) -> bool:
    if isinstance(term, exp.EQ) and isinstance(term.this, exp.Column) and isinstance(term.expression, exp.Column):
        return True
    # `a IS NOT NULL` parses as a negated Is; `NOT a IS NULL` as Not wrapping one.
    negated = isinstance(term, exp.Not)
    check = term.this if negated else term
    if not isinstance(check, exp.Is) or not isinstance(check.expression, exp.Null):
        return False
    return negated != bool(check.args.get("negate"))


def _referenced_tables(statement: exp.Expression) -> set[str]:
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
        if isinstance(expression, exp.Literal) and expression.is_int and int(expression.this) <= cap:
            return statement
    return statement.limit(cap)


def _parse_reason(exc: Exception) -> str:
    text = _ANSI.sub("", str(exc))
    line = text.splitlines()[0].strip() if text else ""
    return line[:200] or "SQL could not be parsed"
