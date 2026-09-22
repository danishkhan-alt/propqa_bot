from enum import Enum


class APIErrorCode(str, Enum):
    """Top-level error categories for this API."""

    VALIDATION = "VALIDATION"
    AUTH = "AUTH"
    USER = "USER"
    CHAT = "CHAT"
    AI = "AI"
    SYSTEM = "SYSTEM"
