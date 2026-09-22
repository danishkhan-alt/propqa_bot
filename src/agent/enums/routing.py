from enum import Enum


class Route(str, Enum):
    """Answer from the model, or look the fact up."""

    DIRECT_ANSWER = "direct_answer"
    NEED_DB = "need_db"


class TurnKind(str, Enum):
    """How this turn relates to the previous database lookup."""

    NEW = "new"
    REFINE = "refine"
    PIVOT = "pivot"


class Intent(str, Enum):
    """What shape of result the user wants. Defaults depend on this, not on a fixed phrase."""

    LIST = "list"
    LOOKUP = "lookup"
    AGGREGATE = "aggregate"
    TREND = "trend"
    COMPARE = "compare"
    RANK = "rank"
    ASSESS = "assess"
    OTHER = "other"
