"""Fixed vocabularies for memory rows, clusters, and preference slots."""

from __future__ import annotations

from enum import Enum


class MemoryType(str, Enum):
    PROFILE = "profile"
    PREFERENCE = "preference"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    GOAL = "goal"
    EPHEMERAL = "ephemeral"


class MemoryProvenance(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    SYSTEM = "system"
    SUMMARIZED = "summarized"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DELETED = "deleted"
    CONTRADICTED = "contradicted"


class MemoryCluster(str, Enum):
    PROPERTY_PREFS = "property_prefs"
    BUDGET = "budget"
    LOCATION = "location"
    PERSONA = "persona"
    GOAL = "goal"
    PERSONAL = "personal"
    WORK = "work"
    TRAVEL = "travel"


class PreferenceSlot(str, Enum):
    BEDROOMS = "bedrooms"
    BUDGET_MAX = "budget_max"
    PREFERRED_LOCATION = "preferred_location"
    PROXIMITY_METRO = "proximity_metro"
    PURPOSE = "purpose"
    FURNISHED = "furnished"
    PERSONA = "persona"
    PROJECTION_PREF = "projection_pref"
    ACTIVE_GOAL = "active_goal"


DEFAULT_CLUSTERS: tuple[MemoryCluster, ...] = (
    MemoryCluster.PROPERTY_PREFS,
    MemoryCluster.BUDGET,
    MemoryCluster.LOCATION,
    MemoryCluster.PERSONA,
    MemoryCluster.GOAL,
)

ALL_CLUSTERS: frozenset[MemoryCluster] = frozenset(MemoryCluster)

EXCLUSIVE_SLOTS_WITHOUT_COLUMN: frozenset[PreferenceSlot] = frozenset(
    {
        PreferenceSlot.PERSONA,
        PreferenceSlot.PROJECTION_PREF,
        PreferenceSlot.ACTIVE_GOAL,
    }
)
