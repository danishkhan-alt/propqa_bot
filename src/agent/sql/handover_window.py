"""Future handover window for new, launching, and off-plan projects.

"Before 2030" on a new-project question is the start of the current month through the
end of 2030. A later turn keeps that window, and a follow-up about "these" stays on the
projects already shown. Ready or already-handed-over questions do not get the window.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime

import sqlglot
from sqlglot import exp

from common.services.app_clock import AppClock

NEW_OFFPLAN_TABLE = "offplan_projects_new"
LEGACY_OFFPLAN_TABLE = "offplan_projects"
MAX_SHORTLIST = 20

_BUDGET_AED = {
    "under_1m": (None, 1_000_000),
    "1m_2m": (1_000_000, 2_000_000),
    "2m_4m": (2_000_000, 4_000_000),
    "4m_plus": (4_000_000, None),
}
_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_FUTURE_LIST = re.compile(
    rf"\b(?:projects?|developments?|launches?)\b.{{0,80}}\b(?:new|upcoming|launch(?:ing|es)?|will\s+launch|off[\s-]?plan|under\s+construction)\b"
    rf"|\b(?:new|upcoming|launch(?:ing|es)?|will\s+launch|off[\s-]?plan|under\s+construction)\b.{{0,80}}\b(?:projects?|developments?|launches?)\b",
    re.I | re.S,
)
_READY = re.compile(
    r"\b(?:ready\s+to\s+move(?:\s+in(?:to)?)?|something\s+ready|move[\s-]?in\s+now|"
    r"ready\s+(?:homes?|properties|apartments?|villas?|projects?|units?))\b",
    re.I,
)
_PAST_HANDOVER = re.compile(
    r"\b(?:already\s+handed(?:\s+over)?|handover\s+was|was\s+handed\s+over|"
    r"handed\s+over\s+(?:in|before|on|by)|completed\s+in)\b",
    re.I,
)
_SINGLE_DATE = re.compile(
    r"\b(?:when\s+(?:is|does|will|was)|what(?:'s| is) the (?:handover|completion)|"
    r"handover date (?:of|for))\b",
    re.I,
)
_OFFPLAN = re.compile(r"\boff[\s-]?plan\b", re.I)
_END = re.compile(
    rf"\b(?:before|by|until|through|till|up\s+to|no\s+later\s+than)"
    rf"(?:\s+the)?(?:\s+end\s+of)?"
    rf"\s+(?:(?P<month>{_MONTH_PATTERN})\s+)?(?P<year>20\d{{2}})\b",
    re.I,
)
_ANAPHORA = re.compile(
    r"\b(?:these|those|them|their|one of|which of|you mention(?:ed)?|the projects?)\b",
    re.I,
)
_PROJECT_ATTRIBUTE = re.compile(
    r"\b(?:their|them|those|these)\b.{0,48}\b(?:developers?|builders?|prices?|handovers?|payment\s+plans?)\b"
    r"|\b(?:developers?|builders?|who\s+(?:built|is\s+building|builds)|prices?|handovers?|payment\s+plans?)\b"
    r".{0,48}\b(?:their|them|those|these|the\s+projects?)\b"
    r"|\bwho\s+built\s+them\b",
    re.I | re.S,
)
_PROJECT_NAME_COLUMNS = frozenset({"project_name_en", "project_name"})
_ADVICE = re.compile(r"\b(?:suggest|recommend|which\s+one|invest)\b", re.I)
_PROFILE = re.compile(
    r"\b(?:my budget|budget is|open to off[\s-]?plan|i(?:'m| am) open|"
    r"as an investment|it(?:'s| is) an investment)\b",
    re.I,
)
_LISTING_WORDS = re.compile(r"\b(?:propert(?:y|ies)|listings?|units?|apartments?|villas?|flats?)\b", re.I)
_FOR_PRIOR = re.compile(
    r"\b(?:for|of|in)\s+(?:those|these|them|that|the projects?|the ones?)\b"
    r"|\b(?:you mention(?:ed)?|those projects|these projects)\b",
    re.I,
)
_QUARTER = re.compile(r"\bQ([1-4])\s*(20\d{2})\b", re.I)
_RELATIVE_YEAR = re.compile(r"\b(early|mid|late)\s*[- ]?\s*(20\d{2})\b", re.I)
_MONTH_YEAR = re.compile(rf"\b({_MONTH_PATTERN})\s+(20\d{{2}})\b", re.I)
_YEAR = re.compile(r"\b(20\d{2})\b")
_HANDOVER_KEYS = (
    "handover_date",
    "completion_date",
    "project_end_date",
    "expected_completion_date",
    "project_completion_date",
)


@dataclass(frozen=True)
class HandoverWindow:
    """Inclusive handover dates a new or off-plan project list may use."""

    start: date
    until: date | None = None

    def as_dict(self) -> dict[str, str]:
        payload = {"from": self.start.isoformat()}
        if self.until is not None:
            payload["until"] = self.until.isoformat()
        return payload


@dataclass(frozen=True)
class ConstrainedSql:
    sql: str
    retry_error: str | None = None


@dataclass(frozen=True)
class ProjectSearch:
    """What this turn must keep from the project shortlist and the handover window."""

    window: HandoverWindow | None
    names: list[str]
    price_min: float | None
    price_max: float | None
    require_catalog: bool
    clear_window: bool

    def price_payload(self) -> dict[str, float] | None:
        payload: dict[str, float] = {}
        if self.price_min is not None:
            payload["min"] = self.price_min
        if self.price_max is not None:
            payload["max"] = self.price_max
        return payload or None


def month_start(today: date | None = None) -> date:
    current = today or AppClock.now().date()
    return current.replace(day=1)


def budget_bounds(bucket: str | None) -> tuple[float | None, float | None]:
    """AED min and max for a saved budget bucket. An open side is None."""
    return _BUDGET_AED.get(str(bucket or ""), (None, None))


def asks_for_ready(message: str) -> bool:
    return bool(_READY.search(message or ""))


def asks_for_past_handover(message: str) -> bool:
    return bool(_PAST_HANDOVER.search(message or ""))


def asks_for_future_project_list(message: str) -> bool:
    """A list of projects still to launch, not one project's date and not a finished building."""
    text = message or ""
    if asks_for_ready(text) or asks_for_past_handover(text) or is_single_project_date(text):
        return False
    return bool(_FUTURE_LIST.search(text))


def is_single_project_date(message: str) -> bool:
    text = message or ""
    if _FUTURE_LIST.search(text):
        return False
    return bool(_SINGLE_DATE.search(text))


def asks_for_project_attribute(message: str) -> bool:
    """Their developers, prices, or handover: a column on the projects, not a new list of that column."""
    return bool(_PROJECT_ATTRIBUTE.search(message or ""))


def wants_project_listings(message: str, projects: list[dict] | None) -> bool:
    """The user wants units in the projects already shown, not another catalog list."""
    if not projects:
        return False
    text = message or ""
    return bool(_LISTING_WORDS.search(text) and (_FOR_PRIOR.search(text) or _ANAPHORA.search(text)))


def keeps_shortlist(message: str, route_names: list, projects: list[dict] | None) -> bool:
    """A follow-up about the projects just shown, with no new place named in the message."""
    if not projects or asks_for_ready(message) or asks_for_past_handover(message):
        return False
    if _names_a_different_place(message, route_names, projects):
        return False
    if asks_for_future_project_list(message) and not _ANAPHORA.search(message or ""):
        return False
    if wants_project_listings(message, projects):
        return True
    return bool(_ANAPHORA.search(message or "") or _ADVICE.search(message or "") or _PROFILE.search(message or ""))


def resolve_handover_window(
    message: str,
    carried: dict | None = None,
    *,
    timeline: str | None = None,
    today: date | None = None,
) -> HandoverWindow | None:
    """The window for this turn, or None when the question is not about a future launch."""
    text = message or ""
    if asks_for_ready(text) or asks_for_past_handover(text) or is_single_project_date(text):
        return None
    current = month_start(today)
    end = _parse_end(text)
    previous = _carried_window(carried, current)
    future = (
        asks_for_future_project_list(text)
        or bool(_OFFPLAN.search(text))
        or timeline == "off_plan"
    )
    if future:
        until = end or (previous.until if previous is not None else None)
        return HandoverWindow(start=current, until=until)
    if previous is not None:
        return HandoverWindow(start=current, until=end or previous.until)
    return None


def project_search_for(
    message: str,
    *,
    carried: dict | None,
    timeline: str | None,
    budget_bucket: str | None,
    route_names: list,
    stated_budget: bool,
    today: date | None = None,
) -> ProjectSearch:
    """Window, shortlist names, and price for the SQL this turn is about to run."""
    projects = list((carried or {}).get("projects") or [])
    clear = asks_for_ready(message)
    window = None if clear else resolve_handover_window(message, carried, timeline=timeline, today=today)
    names: list[str] = []
    if not clear and keeps_shortlist(message, route_names, projects) and not wants_project_listings(message, projects):
        names = [str(item["name"]) for item in projects if item.get("name")][:MAX_SHORTLIST]
    low, high = (None, None)
    if names or stated_budget:
        low, high = budget_bounds(budget_bucket)
    return ProjectSearch(
        window=window,
        names=names,
        price_min=low,
        price_max=high,
        require_catalog=bool(window is not None and (asks_for_future_project_list(message) or names)),
        clear_window=clear,
    )


def constrain_offplan_sql(sql: str, search: ProjectSearch) -> ConstrainedSql:
    """Add the handover window, shortlist, and budget, or say why the statement must be redrafted."""
    window = search.window
    if window is None and not search.names and search.price_min is None and search.price_max is None:
        return ConstrainedSql(sql)
    try:
        statement = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return ConstrainedSql(sql)
    if statement is None:
        return ConstrainedSql(sql)
    uses_new = _reads_table(statement, NEW_OFFPLAN_TABLE)
    uses_legacy = _reads_table(statement, LEGACY_OFFPLAN_TABLE)
    if uses_legacy and not uses_new and window is not None:
        return ConstrainedSql(sql, retry_error=_legacy_error(window, search.names))
    if not uses_new:
        if search.require_catalog and window is not None:
            return ConstrainedSql(sql, retry_error=_missing_catalog_error(window, search.names))
        return ConstrainedSql(sql)
    if window is not None:
        _strip_handover_bounds(statement)
    for select, table in _selects_reading(statement, NEW_OFFPLAN_TABLE):
        alias = table.alias_or_name
        if window is not None:
            select.where(
                sqlglot.parse_one(
                    f"{alias}.handover_date >= DATE_TRUNC('month', CURRENT_DATE)",
                    read="postgres",
                ),
                append=True,
                copy=False,
            )
            if window.until is not None:
                select.where(
                    sqlglot.parse_one(
                        f"{alias}.handover_date <= DATE '{window.until.isoformat()}'",
                        read="postgres",
                    ),
                    append=True,
                    copy=False,
                )
        if search.names:
            quoted = ", ".join("'" + name.replace("'", "''") + "'" for name in search.names)
            select.where(
                sqlglot.parse_one(f"{alias}.project_name_en IN ({quoted})", read="postgres"),
                append=True,
                copy=False,
            )
        if search.price_min is not None:
            select.where(
                sqlglot.parse_one(f"{alias}.starting_price >= {int(search.price_min)}", read="postgres"),
                append=True,
                copy=False,
            )
        if search.price_max is not None:
            select.where(
                sqlglot.parse_one(f"{alias}.starting_price <= {int(search.price_max)}", read="postgres"),
                append=True,
                copy=False,
            )
        break
    return ConstrainedSql(statement.sql(dialect="postgres"))


def drop_past_handovers(rows: list[dict], window: HandoverWindow | None) -> tuple[list[dict], bool]:
    """Drop rows whose handover is outside the window. Returns kept rows and whether any were removed."""
    if window is None or not rows:
        return list(rows or []), False
    kept: list[dict] = []
    removed = False
    for row in rows:
        when = _row_handover(row)
        if when is None:
            kept.append(row)
            continue
        if when < window.start or (window.until is not None and when > window.until):
            removed = True
            continue
        kept.append(row)
    return kept, removed


def past_rows_error(window: HandoverWindow) -> str:
    until = f" and on or before {window.until.isoformat()}" if window.until is not None else ""
    return (
        f"Every returned project was handed over before {window.start.isoformat()}. "
        "Use public.offplan_projects_new and keep handover_date on or after "
        f"{window.start.isoformat()}{until}. Do not return projects that have already been handed over."
    )


def select_has_project_name(sql: str) -> bool:
    """True when the statement returns a project name, or a star that would include one."""
    try:
        statement = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return True
    if statement is None:
        return True
    selects = list(statement.find_all(exp.Select))
    if not selects:
        return True
    for select in selects:
        for expression in select.expressions:
            if isinstance(expression, exp.Star):
                return True
            if _names_project(expression):
                return True
    return False


def missing_project_name_error() -> str:
    return (
        "Keep one row per project. Select project_name_en and the attribute asked for "
        "(developer_name_en, starting_price, handover_date, or payment_plan_summary). "
        "Do not return only the developers."
    )


def _names_project(expression: exp.Expression) -> bool:
    if expression.alias and expression.alias.lower() in _PROJECT_NAME_COLUMNS:
        return True
    column = expression if isinstance(expression, exp.Column) else expression.find(exp.Column)
    return isinstance(column, exp.Column) and column.name.lower() in _PROJECT_NAME_COLUMNS


def _legacy_error(window: HandoverWindow, names: list[str]) -> str:
    until = f" AND handover_date <= DATE '{window.until.isoformat()}'" if window.until is not None else ""
    return (
        "public.offplan_projects.handover_date is free text and includes completed projects. "
        "Query public.offplan_projects_new instead, with handover_date >= DATE_TRUNC('month', CURRENT_DATE)"
        f"{until}.{_names_clause(names)}"
    )


def _missing_catalog_error(window: HandoverWindow, names: list[str]) -> str:
    until = f" AND handover_date <= DATE '{window.until.isoformat()}'" if window.until is not None else ""
    return (
        "This asks for new or off-plan projects still to be handed over. "
        "Query public.offplan_projects_new with handover_date >= DATE_TRUNC('month', CURRENT_DATE)"
        f"{until}.{_names_clause(names)}"
    )


def _names_clause(names: list[str]) -> str:
    if not names:
        return ""
    shown = ", ".join(names[:8])
    return f" Filter project_name_en to: {shown}."


def _parse_end(message: str) -> date | None:
    match = _END.search(message or "")
    if match is None:
        return None
    year = int(match.group("year"))
    month_name = (match.group("month") or "").lower()
    if not month_name:
        return date(year, 12, 31)
    month = _MONTHS[month_name]
    return date(year, month, calendar.monthrange(year, month)[1])


def _carried_window(carried: dict | None, start: date) -> HandoverWindow | None:
    raw = (carried or {}).get("handover_window")
    if not isinstance(raw, dict):
        return None
    until = None
    if raw.get("until"):
        try:
            until = date.fromisoformat(str(raw["until"])[:10])
        except ValueError:
            until = None
    if not raw.get("from") and until is None:
        return None
    return HandoverWindow(start=start, until=until)


def _names_a_different_place(message: str, route_names: list, projects: list[dict]) -> bool:
    known = {_norm(str(item.get("name") or "")) for item in projects}
    folded = _norm(message)
    for name in route_names:
        text = _norm(getattr(name, "text", name))
        if not text or text in known:
            continue
        if text in folded:
            return True
    return False


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _reads_table(statement: exp.Expression, bare: str) -> bool:
    return any(_bare_table(table) == bare for table in statement.find_all(exp.Table))


def _selects_reading(statement: exp.Expression, bare: str) -> list[tuple[exp.Select, exp.Table]]:
    found: list[tuple[exp.Select, exp.Table]] = []
    for table in statement.find_all(exp.Table):
        select = table.find_ancestor(exp.Select)
        if select is not None and _bare_table(table) == bare:
            found.append((select, table))
    return found


def _bare_table(table: exp.Table) -> str:
    return table.name.lower()


def _strip_handover_bounds(statement: exp.Expression) -> None:
    for node in list(statement.find_all(exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)):
        if any(isinstance(column, exp.Column) and column.name.lower() == "handover_date" for column in node.find_all(exp.Column)):
            node.replace(exp.true())


def _row_handover(row: dict) -> date | None:
    for key in _HANDOVER_KEYS:
        if key in row and row.get(key) not in (None, ""):
            parsed = parse_handover_date(row.get(key))
            if parsed is not None:
                return parsed
    return None


def parse_handover_date(value: object) -> date | None:
    """A handover value as a date. A quarter or a year uses the last day of that span."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    quarter = _QUARTER.search(text)
    if quarter is not None:
        q = int(quarter.group(1))
        year = int(quarter.group(2))
        end_month = q * 3
        return date(year, end_month, calendar.monthrange(year, end_month)[1])
    relative = _RELATIVE_YEAR.search(text)
    if relative is not None:
        year = int(relative.group(2))
        month = {"early": 3, "mid": 6, "late": 12}[relative.group(1).lower()]
        return date(year, month, calendar.monthrange(year, month)[1])
    named = _MONTH_YEAR.search(text)
    if named is not None:
        month = _MONTHS[named.group(1).lower()]
        year = int(named.group(2))
        return date(year, month, calendar.monthrange(year, month)[1])
    year_only = _YEAR.search(text)
    if year_only is not None:
        year = int(year_only.group(1))
        return date(year, 12, 31)
    return None
