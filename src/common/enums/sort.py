from enum import Enum


class SortDirection(str, Enum):
    """Database sort direction."""

    ASC = "asc"
    DESC = "desc"
