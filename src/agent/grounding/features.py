"""The amenities and views a listing can be tagged with, and matching a user's words to them.

A requirement such as "private gym", "sea view", or "near a mall" matches every stored title
that holds all of its words ("gym" matches Shared Gym and Private Gym), after plurals and
filler words are set aside. Only a requirement that says "view" matches a view: "pool" is
the amenity, not Pool View. Wording the titles never use comes from the catalog's feature
aliases. A close typo matches too. Anything else stays unmatched, so the search can say it
did not check it rather than claim it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.enums.grounding import FeatureKind
from agent.grounding.name_matching import normalize_name, trigram_similarity
from agent.schemas.grounding import GroundedFeature

# Words that say how a feature is wanted, not what it is.
_FILLER_WORDS = frozenset({"a", "an", "the", "with", "has", "have", "having", "and", "or", "of", "to", "access"})
# "near a mall" is how people say what listings store as "Nearby Shopping Malls".
_SAME_WORD = {"near": "nearby", "close": "nearby"}
_VIEW_WORD = "view"
# A typo is only taken when the spelling is this close; looser matches pick unrelated titles.
MIN_TYPO_SIMILARITY = 0.6


@dataclass(frozen=True)
class Feature:
    kind: FeatureKind
    id: int
    title: str


@dataclass(frozen=True)
class FeatureVocabulary:
    """Every amenity and view title, with the words each answers to. Read by every request."""

    features: tuple[Feature, ...] = ()
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def match(self, phrase: str) -> list[Feature]:
        """The features the phrase names, or none."""
        words = feature_words(phrase)
        if not words:
            return []
        aliased = self.aliases.get(" ".join(sorted(words)))
        if aliased is not None:
            titles = {normalize_name(title) for title in aliased}
            return [feature for feature in self.features if normalize_name(feature.title) in titles]
        kind = FeatureKind.VIEW if _VIEW_WORD in words else FeatureKind.AMENITY
        candidates = [feature for feature in self.features if feature.kind is kind]
        containing = [feature for feature in candidates if words <= feature_words(feature.title)]
        if containing:
            return containing
        joined = " ".join(sorted(words))
        return [
            feature
            for feature in candidates
            if trigram_similarity(joined, " ".join(sorted(feature_words(feature.title)))) >= MIN_TYPO_SIMILARITY
        ]


def ground_features(requirements: list[str], vocabulary: FeatureVocabulary) -> list[GroundedFeature]:
    """Each requirement with the amenities and views it names. An unmatched one keeps no ids."""
    grounded: list[GroundedFeature] = []
    for text in requirements:
        matched = vocabulary.match(text)
        grounded.append(
            GroundedFeature(
                text=text,
                amenity_ids=sorted({feature.id for feature in matched if feature.kind is FeatureKind.AMENITY}),
                view_ids=sorted({feature.id for feature in matched if feature.kind is FeatureKind.VIEW}),
                titles=sorted({feature.title for feature in matched}),
            )
        )
    return grounded


def build_feature_vocabulary(features: list[Feature], aliases: dict[str, list[str]]) -> FeatureVocabulary:
    return FeatureVocabulary(
        features=tuple(feature for feature in features if feature_words(feature.title)),
        aliases={" ".join(sorted(feature_words(wording))): tuple(titles) for wording, titles in aliases.items()},
    )


def feature_words(text: str) -> frozenset[str]:
    """The words that say what a feature is: singular, without filler. "Maid's room" is {maid, room}."""
    words = normalize_name(str(text or "").replace("'", "").replace("’", "")).split()
    return frozenset(
        _SAME_WORD.get(word, word) for word in (_singular(word) for word in words) if word not in _FILLER_WORDS
    )


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word
