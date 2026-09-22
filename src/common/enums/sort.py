from enum import Enum


class DBSort(str, Enum):
    """Database sort direction."""

    ASC = "asc"
    DESC = "desc"
