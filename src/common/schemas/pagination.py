from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_PER_PAGE = 10
MAX_PER_PAGE = 100


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
