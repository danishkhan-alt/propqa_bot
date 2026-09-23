from __future__ import annotations

from pydantic import BaseModel, Field


class SqlDraft(BaseModel):
    """One read-only statement proposed for the loaded catalog."""

    sql: str = Field(description="A single PostgreSQL SELECT. No markdown.")
    purpose: str = Field(description="One line: why this statement answers the user.")
