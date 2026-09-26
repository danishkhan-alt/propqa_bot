from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from common.schemas.pagination import PaginationMetadata

T = TypeVar("T")


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


class APIResponse(BaseModel, Generic[T]):
    """Success envelope every happy-path endpoint speaks."""

    result: T | None = None
    status: int = 200


class PaginatedAPIResponse(BaseModel, Generic[T]):
    """Standardized paginated success envelope."""

    result: list[T]
    metadata: PaginationMetadata
    status: int = 200
