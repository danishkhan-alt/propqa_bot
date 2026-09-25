"""Stored spellings of names in the columns each catalog domain declares under `named_values`.

The SQL model filters on the exact stored value instead of guessing an ILIKE pattern.
When a row carries two name columns for the same place (DLD stores the marketing master
project next to the official area), the pair is learned from the data, so "Dubai Marina"
also yields area_name_en = 'Marsa Dubai' without anyone writing that down.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from agent.grounding.names import MatchTier, NameMatcher, normalize_name

MAX_VALUES_PER_COLUMN = 10
# A name counts as the same place as a canonical value when this share of its rows agree.
SAME_PLACE_AGREEMENT = 0.8

# Place kinds, broadest first. A broader kind wins a tie, as with places.
PLACE_KIND_ORDER = {"area": 0, "community": 0, "master_project": 1, "project": 2, "building": 3}
PLACE_GROUP = "place"
# Company names carry legal suffixes ("Emaar Properties (P.J.S.C)"), so every stored name that
# contains the typed name is the same company. A place is different: "Dubai Marina Mall" is
# not "Dubai Marina", so places keep the strongest match only.
GROUPS_MATCHING_CONTAINING_NAMES = frozenset({"developer"})


def name_group(kind: str) -> str:
    """Place kinds are searched together; any other kind (developer, school) on its own."""
    return PLACE_GROUP if kind in PLACE_KIND_ORDER else kind


@dataclass(frozen=True)
class NamedColumn:
    """A column whose values are names users type. Declared in the domain YAML."""

    table: str
    column: str
    kind: str
    same_place_as: str | None = None


@dataclass(frozen=True)
class StoredValue:
    table: str
    column: str
    value: str
    kind: str
    row_count: int = 0
    # Set when this value was reached from another name on the same rows.
    same_place_as: str | None = None

    def as_prompt(self) -> dict:
        found = {"column": f"{self.table}.{self.column}", "value": self.value}
        if self.same_place_as:
            found["same_place_as"] = self.same_place_as
        return found


ValueKey = tuple[str, str, str]


class StoredValueIndex:
    def __init__(
        self,
        values: Iterable[StoredValue],
        same_place: Mapping[ValueKey, StoredValue],
        aliases: Mapping[str, list[str]] | None = None,
    ) -> None:
        self._values: dict[ValueKey, StoredValue] = {}
        self._matchers: dict[tuple[str, str], NameMatcher[ValueKey]] = defaultdict(NameMatcher)
        extra_names = _alias_names(aliases or {})
        for value in values:
            key = (value.table, value.column, value.value)
            self._values[key] = value
            names = [value.value, *extra_names.get(normalize_name(value.value), [])]
            self._matchers[(value.table, name_group(value.kind))].add(key, names)
        self._same_place = dict(same_place)

    def __len__(self) -> int:
        return len(self._values)

    def find(
        self,
        spellings: list[str],
        tables: Iterable[str],
        groups: set[str] | None = None,
    ) -> list[StoredValue]:
        """Stored values for a name, per table and name group. `groups` None searches every group.

        `spellings` are tried together and the strongest match tier wins.
        """
        wanted = set(tables)
        found: list[StoredValue] = []
        for (table, group), matcher in sorted(self._matchers.items()):
            if table in wanted and (groups is None or group in groups):
                containing = group in GROUPS_MATCHING_CONTAINING_NAMES
                found.extend(self._find_in_matcher(matcher, spellings, containing=containing))
        return found

    def _find_in_matcher(
        self,
        matcher: NameMatcher[ValueKey],
        spellings: list[str],
        *,
        containing: bool,
    ) -> list[StoredValue]:
        find = matcher.find_containing if containing else matcher.find
        hits = [hit for spelling in spellings for hit in find(spelling)]
        if not hits:
            return []
        # A table may store more than one spelling of a name, so every hit at the strongest tier
        # counts. When containing names match, exact and containing hits count alike.
        best_tier = max(hit.tier for hit in hits)
        if containing:
            best_tier = min(best_tier, MatchTier.WORDS)
        best_keys = list(dict.fromkeys(hit.key for hit in hits if hit.tier >= best_tier))
        values = [self._values[key] for key in best_keys]
        broadest = min(_kind_rank(value.kind) for value in values)
        kept = sorted(
            (value for value in values if _kind_rank(value.kind) == broadest),
            key=lambda value: -value.row_count,
        )[:MAX_VALUES_PER_COLUMN]
        linked = [
            self._same_place[key]
            for key in ((value.table, value.column, value.value) for value in kept)
            if key in self._same_place
        ]
        return [*kept, *linked]


def learn_same_place(
    column: NamedColumn,
    canonical_kind: str,
    pair_counts: Iterable[tuple[str, str, int]],
) -> dict[ValueKey, StoredValue]:
    """Map each value of `column` to the `same_place_as` value its rows overwhelmingly carry."""
    totals: dict[str, int] = defaultdict(int)
    top: dict[str, tuple[str, int]] = {}
    for name, canonical, count in pair_counts:
        if not name or not canonical:
            continue
        totals[name] += count
        if count > top.get(name, ("", 0))[1]:
            top[name] = (canonical, count)
    learned: dict[ValueKey, StoredValue] = {}
    for name, (canonical, count) in top.items():
        if normalize_name(canonical) == normalize_name(name) or count < SAME_PLACE_AGREEMENT * totals[name]:
            continue
        learned[(column.table, column.column, name)] = StoredValue(
            table=column.table,
            column=column.same_place_as or "",
            value=canonical,
            kind=canonical_kind,
            row_count=count,
            same_place_as=f"{column.column} = '{name}'",
        )
    return learned


def _alias_names(aliases: Mapping[str, list[str]]) -> dict[str, list[str]]:
    """Stored name (normalised) to the extra wording people use for it."""
    extra: dict[str, list[str]] = defaultdict(list)
    for wording, stored_names in aliases.items():
        for stored in stored_names or []:
            extra[normalize_name(stored)].append(wording)
    return extra


def _kind_rank(kind: str) -> int:
    return PLACE_KIND_ORDER.get(kind, len(PLACE_KIND_ORDER))
