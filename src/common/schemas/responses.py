from __future__ import annotations

from pydantic import BaseModel


class FieldProblem(BaseModel):
    """One field that failed validation."""

    field: str
    problem: str


class ProblemDetails(BaseModel):
    """RFC 9457 Problem Details, plus machine codes for this API."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    code: str
    subcode: str
    trace_id: str | None = None
    errors: list[FieldProblem] | None = None
