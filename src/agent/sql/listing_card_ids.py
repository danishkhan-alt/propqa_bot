"""Listing cards are ids. The frontend loads each property from that id."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from agent.enums.routing import Intent
from agent.schemas.routes import as_domain_route, as_query_route
from agent.sql.guard import live_listing_id_column
from agent.states.chat import ChatState

_LISTING_INTENTS = frozenset({Intent.LIST, Intent.RANK})


def is_listing_list_request(state: ChatState) -> bool:
    """The user asked to see properties, and the listings pack is loaded."""
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    if query is None or domain is None:
        return False
    if query.intent not in _LISTING_INTENTS:
        return False
    return "listings" in domain.domain_ids


def listing_card_ids_from_rows(state: ChatState, rows: list[dict], sql: str = "") -> list[str]:
    """Ids to render as listing cards, in row order.

    Only a column the statement reads from public.properties.id counts: a card is loaded from
    that table, so a DLD unit, building, or community id would show an unrelated listing.
    """
    column = live_listing_id_column(sql)
    if column is None:
        return []
    columns = (column,)
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = _first_listing_id_in_row(row, columns)
        if text is None or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _first_listing_id_in_row(row: dict, columns: tuple[str, ...]) -> str | None:
    for column in columns:
        text = _id_text(row.get(column))
        if text is not None:
            return text
    return None


def _id_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return str(int(value))
    if isinstance(value, Decimal):
        return _whole_number(value)
    text = str(value).strip()
    if not text:
        return None
    if "." in text:
        try:
            return _whole_number(Decimal(text))
        except InvalidOperation:
            return None
    return text


def _whole_number(value: Decimal) -> str | None:
    if value != value.to_integral_value():
        return None
    return str(int(value))
