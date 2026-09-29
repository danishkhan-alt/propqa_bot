from enum import Enum


class APIErrorCode(str, Enum):
    """Top-level error categories for this API."""

    VALIDATION = "VALIDATION"
    AUTH = "AUTH"
    USER = "USER"
    SYSTEM = "SYSTEM"
