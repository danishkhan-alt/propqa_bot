"""Name normalisation and matching shared by the place tree and the stored-value index.

A phrase matches a stored name in one of three tiers, strongest first:
exact (same normalised text), words (every word of the phrase is a word of the name),
and fuzzy (trigram similarity, for typos). A stronger tier always wins over a weaker one.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from enum import IntEnum
from typing import Generic, TypeVar

_BRACKETED = re.compile(r"\(([^)]*)\)")
_NON_WORD = re.compile(r"[^0-9a-z]+")

FUZZY_THRESHOLD = 0.45

Key = TypeVar("Key", bound=Hashable)


class MatchTier(IntEnum):
    FUZZY = 1
    WORDS = 2
    EXACT = 3


@dataclass(frozen=True)
class NameHit(Generic[Key]):
    key: Key
    tier: MatchTier
    # Share of the stored name the phrase covers. "marina" covers half of "dubai marina".
    coverage: float


def normalize_name(text: str) -> str:
    """Lowercase words only. "DownTown Dubai" and "downtown-dubai" normalise the same."""
    return " ".join(_NON_WORD.sub(" ", str(text or "").lower()).split())


def without_brackets(text: str) -> str:
    """ "Jumeirah Village Circle (JVC)" becomes "Jumeirah Village Circle"."""
    return " ".join(_BRACKETED.sub(" ", str(text or "")).split())


def name_variants(text: str) -> set[str]:
    """Normalised spellings a stored name answers to.

    "Jumeirah Village Circle (JVC)" answers to the full name, to the name without the
    bracket, and to the bracketed short form on its own.
    """
    raw = str(text or "")
    variants = {normalize_name(raw), normalize_name(_BRACKETED.sub(" ", raw))}
    variants.update(normalize_name(inner) for inner in _BRACKETED.findall(raw))
    return {variant for variant in variants if variant}


def trigrams(text: str) -> set[str]:
    padded = f"  {text} "
    return {padded[index : index + 3] for index in range(len(padded) - 2)}


def trigram_similarity(left: str, right: str) -> float:
    """Same measure as pg_trgm similarity(): shared trigrams over all trigrams."""
    left_grams, right_grams = trigrams(left), trigrams(right)
    union = left_grams | right_grams
    return len(left_grams & right_grams) / len(union) if union else 0.0


class NameMatcher(Generic[Key]):
    """Finds the keys whose names best match a phrase. Built once, read by every request."""

    def __init__(self) -> None:
        self._keys_by_name: dict[str, set[Key]] = defaultdict(set)
        self._names_by_word: dict[str, set[str]] = defaultdict(set)
        self._names_by_trigram: dict[str, set[str]] = defaultdict(set)

    def add(self, key: Key, names: Iterable[str]) -> None:
        for name in names:
            normalized = normalize_name(name)
            if not normalized:
                continue
            if normalized not in self._keys_by_name:
                for word in normalized.split():
                    self._names_by_word[word].add(normalized)
                for gram in trigrams(normalized):
                    self._names_by_trigram[gram].add(normalized)
            self._keys_by_name[normalized].add(key)

    def find(self, phrase: str) -> list[NameHit[Key]]:
        """Every key in the strongest tier that matched, with its best coverage."""
        normalized = normalize_name(phrase)
        if not normalized:
            return []
        for tier, names in (
            (MatchTier.EXACT, self._exact(normalized)),
            (MatchTier.WORDS, self._containing_words(normalized)),
            (MatchTier.FUZZY, self._similar(normalized)),
        ):
            if names:
                return self._hits(normalized, names, tier)
        return []

    def _exact(self, normalized: str) -> list[str]:
        return [normalized] if normalized in self._keys_by_name else []

    def _containing_words(self, normalized: str) -> list[str]:
        candidates: set[str] | None = None
        for word in normalized.split():
            names = self._names_by_word.get(word, set())
            candidates = set(names) if candidates is None else candidates & names
            if not candidates:
                return []
        return sorted(candidates or ())

    def _similar(self, normalized: str) -> list[str]:
        phrase_grams = trigrams(normalized)
        shared: Counter[str] = Counter()
        for gram in phrase_grams:
            shared.update(self._names_by_trigram.get(gram, ()))
        # similarity = shared / union, and union >= the phrase's own trigrams, so a name
        # below this many shared trigrams can never reach the threshold.
        floor = FUZZY_THRESHOLD * len(phrase_grams)
        return [
            name
            for name, count in shared.items()
            if count >= floor and trigram_similarity(normalized, name) >= FUZZY_THRESHOLD
        ]

    def _hits(self, normalized: str, names: list[str], tier: MatchTier) -> list[NameHit[Key]]:
        phrase_words = len(normalized.split())
        best: dict[Key, float] = {}
        for name in names:
            coverage = min(1.0, phrase_words / len(name.split()))
            if tier is MatchTier.FUZZY:
                coverage = trigram_similarity(normalized, name)
            for key in self._keys_by_name[name]:
                best[key] = max(best.get(key, 0.0), coverage)
        return [NameHit(key=key, tier=tier, coverage=coverage) for key, coverage in best.items()]
