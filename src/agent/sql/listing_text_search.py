"""Turn leftover listing requirements into a bound full-text query.

The amenity and view catalog cannot name everything a buyer asks for ("high ceilings",
"large windows"). Those phrases are matched against public.properties.search_vector.
The user's words stay in a bound parameter. They are never written into the SQL text.

A phrase is quoted so the English web search treats it as a phrase. Several phrases
are joined with a space, which means all of them. Generic trailing words ("room",
"living") are dropped when a more specific word remains, because "double height living
room" would otherwise require the word "room" and miss listings that only say
"double height".
"""

from __future__ import annotations

from functools import lru_cache

from agent.grounding.features import FEATURE_FILLER_WORDS
from agent.grounding.name_matching import normalize_name
from catalog import load_listing_text_synonyms
from config import ActiveConfig

# Dropped from the end of a phrase when a more specific word is still left.
_GENERIC_TAILS = frozenset({"room", "area", "space", "living"})


def build_text_query(requirements: list[str]) -> str | None:
    """Quoted phrases for websearch_to_tsquery, or None when nothing searchable remains."""
    return _join_phrases(_cleaned_phrases(requirements), joiner=" ")


def broaden_with_synonyms(requirements: list[str]) -> str | None:
    """The same phrases OR their listing-text synonyms, or None when no synonym applies.

    websearch_to_tsquery treats OR as looser than a space (AND). This is only used
    after the required phrase match found nothing.
    """
    phrases = _cleaned_phrases(requirements)
    if not phrases:
        return None
    collected: list[str] = []
    expanded = False
    for phrase in phrases:
        group = _synonym_group(phrase)
        extras = [item for item in group if item != phrase] if group else []
        if extras:
            expanded = True
            collected.extend(group or [phrase])
        else:
            collected.append(phrase)
    if not expanded:
        return None
    return _join_phrases(_unique(collected), joiner=" OR ")


def _cleaned_phrases(requirements: list[str]) -> list[str]:
    min_word_chars = ActiveConfig.LISTING_TEXT_MIN_WORD_CHARS
    phrases: list[str] = []
    for text in requirements:
        words = _phrase_words(text, min_word_chars)
        if not words:
            continue
        phrase = " ".join(words)
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _phrase_words(text: str, min_word_chars: int) -> list[str]:
    words = [
        word
        for word in normalize_name(text).split()
        if word not in FEATURE_FILLER_WORDS and len(word) >= min_word_chars
    ]
    while len(words) > 1 and words[-1] in _GENERIC_TAILS:
        if any(word not in _GENERIC_TAILS for word in words[:-1]):
            words.pop()
        else:
            break
    return words


def _join_phrases(phrases: list[str], *, joiner: str) -> str | None:
    if not phrases:
        return None
    max_chars = ActiveConfig.LISTING_TEXT_QUERY_MAX_CHARS
    kept: list[str] = []
    for phrase in phrases:
        if len(joiner.join(_quote(item) for item in [*kept, phrase])) <= max_chars:
            kept.append(phrase)
            continue
        if kept:
            break
        shortened = _shorten_to_fit(phrase, max_chars)
        return _quote(shortened) if shortened else None
    if not kept:
        return None
    return joiner.join(_quote(phrase) for phrase in kept)


def _shorten_to_fit(phrase: str, max_chars: int) -> str | None:
    words = phrase.split()
    while words and len(_quote(" ".join(words))) > max_chars:
        words.pop()
    return " ".join(words) if words else None


def _quote(phrase: str) -> str:
    cleaned = " ".join(phrase.replace('"', " ").split())
    return f'"{cleaned}"'


def _synonym_group(phrase: str) -> tuple[str, ...] | None:
    key = normalize_name(phrase)
    for group in _synonym_groups():
        if key in group:
            return group
    return None


@lru_cache(maxsize=1)
def _synonym_groups() -> tuple[tuple[str, ...], ...]:
    groups: list[tuple[str, ...]] = []
    for group in load_listing_text_synonyms():
        phrases = _unique(normalize_name(phrase) for phrase in group if normalize_name(phrase))
        if phrases:
            groups.append(tuple(phrases))
    return tuple(groups)


def _unique(phrases) -> list[str]:
    seen: list[str] = []
    for phrase in phrases:
        if phrase not in seen:
            seen.append(phrase)
    return seen
