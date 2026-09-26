"""What a name in the message refers to, and the closed sets a listing search filters and sorts by."""

from __future__ import annotations

from enum import Enum


class MentionKind(str, Enum):
    """What a name in the message refers to. Decides where it is looked up."""

    PLACE = "place"
    DEVELOPER = "developer"
    OTHER = "other"


class ListingSort(str, Enum):
    NEWEST = "newest"
    PRICE_LOW = "price_low"
    PRICE_HIGH = "price_high"
    SIZE_LARGE = "size_large"


# "any" is an explicit value rather than null: the router's output schema may hold at most
# 16 nullable (union-typed) fields, and a named "any" is chosen more reliably than a null.
class ListingPurpose(str, Enum):
    ANY = "any"
    SALE = "sale"
    RENT = "rent"


class Furnishing(str, Enum):
    ANY = "any"
    FURNISHED = "furnished"
    UNFURNISHED = "unfurnished"
    SEMI_FURNISHED = "semi-furnished"


class Completion(str, Enum):
    ANY = "any"
    READY = "ready"
    OFF_PLAN = "off_plan"
