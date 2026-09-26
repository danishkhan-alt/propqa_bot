from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100


class PaginationMetadata(BaseModel):
    total: int
    per_page: int
    page: int
    last_page: int
    has_next: bool
    has_previous: bool


class PageRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=DEFAULT_PER_PAGE, ge=1, le=MAX_PER_PAGE)


def build_page_request(*, page: int = 1, per_page: int | None = None) -> PageRequest:
    """One page of any list. Properties and agents use the same window.

    A count the user asked for replaces the default page size, and cannot
    exceed ``MAX_PER_PAGE``.
    """
    size = DEFAULT_PER_PAGE if not per_page else min(per_page, MAX_PER_PAGE)
    return PageRequest(page=page, per_page=size)


def build_pagination_metadata(*, total: int, page: int, per_page: int) -> PaginationMetadata:
    last_page = max(1, (total + per_page - 1) // per_page) if total else 1
    current = min(page, last_page)
    return PaginationMetadata(
        total=total,
        per_page=per_page,
        page=current,
        last_page=last_page,
        has_next=current < last_page,
        has_previous=current > 1,
    )


def paginate(items: Sequence[Any], request: PageRequest) -> tuple[list[Any], PaginationMetadata]:
    """One page of an in-memory sequence. Prefer ``page_meta`` when SQL already counted."""

    metadata = build_pagination_metadata(total=len(items), page=request.page, per_page=request.per_page)
    start = (metadata.page - 1) * request.per_page
    end = start + request.per_page
    return list(items[start:end]), metadata
