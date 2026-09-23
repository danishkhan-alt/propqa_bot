"""Fixed vocabularies for memory rows and clusters."""

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


DEFAULT_CLUSTERS: tuple[MemoryCluster, ...] = (
    MemoryCluster.PROPERTY_PREFS,
    MemoryCluster.BUDGET,
    MemoryCluster.LOCATION,
    MemoryCluster.PERSONA,
    MemoryCluster.GOAL,
)

ALL_CLUSTERS: frozenset[MemoryCluster] = frozenset(MemoryCluster)
