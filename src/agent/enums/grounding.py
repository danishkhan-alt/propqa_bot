"""How well a name matched, and how much ground a place covers."""

from enum import IntEnum


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
