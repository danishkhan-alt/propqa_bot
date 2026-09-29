"""How well a name matched, how much ground a place covers, and what kind of feature a listing has."""

from enum import IntEnum, StrEnum


class MatchTier(IntEnum):
    """How closely a name matched. A higher tier beats a lower one."""

    FUZZY = 1
    WORDS = 2
    EXACT = 3


class Breadth(IntEnum):
    """How much ground a place covers. A broader place wins a tie: "marina" is the area, not a tower."""

    REGION = 0
    AREA = 1
    PROJECT = 2
    BUILDING = 3


class FeatureKind(StrEnum):
    """Where a listing feature is stored: public.amenities or public.views."""

    AMENITY = "amenity"
    VIEW = "view"
