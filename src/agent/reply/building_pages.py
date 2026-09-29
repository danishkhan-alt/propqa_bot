"""Links to the building pages on propqa.ai, for the buildings a reply is about.

Every building with a page has a row in public.revamp_buildings. Its slug_en is the page's
path and its location_id is the building's node in public.locations_v2, the tree places are
grounded in. A reply links a building the user named, and each building the lookup rows name,
so a comparison or a ranked list links every building it shows.

The links are chosen here, from the data. The answer model is only told which pages are
linked, so a link on screen always leads to a page that exists.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent.enums.grounding import Breadth
from agent.grounding.name_matching import normalize_name
from agent.schemas.grounding import Grounding

MAX_BUILDING_PAGES = 6
BUILDING_PAGES_TABLE = "public.revamp_buildings"


@dataclass(frozen=True)
class BuildingPage:
    name: str
    community: str
    slug: str
    location_id: int | None = None

    def to_ui_payload(self) -> dict[str, str]:
        """The UI builds the link from the slug, as it does for listing cards."""
        return {"name": self.name, "community": self.community, "slug": self.slug}


class BuildingPageDirectory:
    """Every building page, found by its location node or its exact name."""

    def __init__(self, pages: Iterable[BuildingPage] = ()) -> None:
        self._by_location_id: dict[int, BuildingPage] = {}
        self._by_name: dict[str, BuildingPage] = {}
        for page in pages:
            if page.location_id is not None:
                self._by_location_id.setdefault(page.location_id, page)
            self._by_name.setdefault(normalize_name(page.name), page)

    def __len__(self) -> int:
        return len(self._by_name)

    def at_location(self, location_ids: Iterable[int]) -> list[BuildingPage]:
        return [
            self._by_location_id[location_id]
            for location_id in location_ids
            if location_id in self._by_location_id
        ]

    def named(self, text: Any) -> BuildingPage | None:
        """The page whose building is called exactly this, ignoring case and punctuation."""
        if not isinstance(text, str):
            return None
        key = normalize_name(text)
        return self._by_name.get(key) if key else None


def building_pages_from_rows(rows: list[dict[str, Any]]) -> list[BuildingPage]:
    """Pages from public.revamp_buildings rows. A row without a slug has no page."""
    pages: list[BuildingPage] = []
    for row in rows:
        name = str(row.get("building_name") or "").strip()
        slug = str(row.get("slug_en") or "").strip().strip("/")
        if not name or not slug:
            continue
        location_id = row.get("location_id")
        pages.append(
            BuildingPage(
                name=name,
                community=str(row.get("community") or "").strip(),
                slug=slug,
                location_id=int(location_id) if location_id is not None else None,
            )
        )
    return pages


def pick_building_pages(
    directory: BuildingPageDirectory | None,
    grounding: Grounding | None,
    rows: list[dict[str, Any]],
) -> list[BuildingPage]:
    """The pages for the buildings this turn is about: those the user named, then those the rows name.

    Some building names are common words ("Aura", "The One"). A name found only in the rows
    is linked when it lies inside a place the user named, or when they named no place, so a
    project elsewhere that shares the name is never linked.
    """
    if directory is None or not len(directory):
        return []
    named, scope = _pages_the_user_named(directory, grounding)
    picked: dict[str, BuildingPage] = {page.slug: page for page in named}
    for row in rows:
        for value in row.values():
            page = directory.named(value)
            if page is None or page.slug in picked:
                continue
            if scope and page.location_id not in scope:
                continue
            picked[page.slug] = page
    return list(picked.values())[:MAX_BUILDING_PAGES]


def _pages_the_user_named(
    directory: BuildingPageDirectory, grounding: Grounding | None
) -> tuple[list[BuildingPage], set[int]]:
    """Pages for the buildings the user named, and every node under the broader places they named."""
    pages: list[BuildingPage] = []
    scope: set[int] = set()
    for name in grounding.names if grounding is not None else []:
        place = name.place
        # A broader place's ids hold every building in it, so only a building is linked by id.
        named = directory.at_location(place.v2_ids) if place is not None and place.breadth is Breadth.BUILDING else []
        # A stored name can match on part of its words: "Dubai Marina" finds "Dubai Marina Mall".
        # Only a building called exactly what the user typed, or what the place is titled, is theirs.
        spellings = {normalize_name(name.text), normalize_name(place.title) if place is not None else ""}
        named += [
            page
            for page in (directory.named(stored.value) for stored in name.stored if stored.table == BUILDING_PAGES_TABLE)
            if page is not None and normalize_name(page.name) in spellings
        ]
        if named:
            pages.extend(named)
        elif place is not None:
            scope.update(place.v2_ids)
    return pages, scope
