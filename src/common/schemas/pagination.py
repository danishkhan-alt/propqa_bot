from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

MAX_PER_PAGE = 100


class PaginationMetaData(BaseModel):
    total: int
    per_page: int
    page: int
    last_page: int
    has_next: bool
    has_previous: bool


class PageRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=MAX_PER_PAGE)


def page_meta(*, total: int, page: int, per_page: int) -> PaginationMetaData:
    last_page = max(1, (total + per_page - 1) // per_page) if total else 1
    current = min(page, last_page)
    return PaginationMetaData(
        total=total,
        per_page=per_page,
        page=current,
        last_page=last_page,
        has_next=current < last_page,
        has_previous=current > 1,
    )


def paginate(items: Sequence[Any], request: PageRequest) -> tuple[list[Any], PaginationMetaData]:
    """One page of an in-memory sequence. Prefer ``page_meta`` when SQL already counted."""

    metadata = page_meta(total=len(items), page=request.page, per_page=request.per_page)
    start = (metadata.page - 1) * request.per_page
    end = start + request.per_page
    return list(items[start:end]), metadata
