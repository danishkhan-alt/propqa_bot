from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class SqlDraft(BaseModel):
    """One read-only statement proposed for the loaded catalog."""

    sql: str = Field(description="A single PostgreSQL SELECT. No markdown.")
    purpose: str = Field(description="One line: why this statement answers the user.")


@dataclass(frozen=True)
class SqlPage:
    """Rows the statement actually returned, already capped."""

    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool
    duration_ms: int


@dataclass(frozen=True)
class SegmentRule:
    """How one table's rows split into kinds of property that must not share an average.

    segments: an average must group by or filter on at least one of these (villa or flat,
    bedrooms, index series). basis: it must group by or filter on every one of these
    (sale or rent, sales or mortgages), since those are different measures, not a mix.
    """

    table: str
    columns: frozenset[str]
    segments: tuple[str, ...]
    basis: tuple[str, ...] = ()
