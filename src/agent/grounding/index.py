"""The grounding index: places and stored names, read from the warehouse and kept in memory.

It is read-only and small (tens of thousands of names), so each process keeps its own copy.
Loading runs in a background thread, started when the app starts, and a stale copy keeps
serving while the next one loads. A turn that arrives before the first copy is ready waits
for it, up to a limit, since without it no name the user typed can be matched.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from psycopg import sql

from agent.enums.grounding import Breadth, FeatureKind
from agent.grounding.features import Feature, FeatureVocabulary, build_feature_vocabulary
from agent.grounding.places import LEGACY_BREADTH, V2_BREADTH, PlaceDirectory, build_place_directory
from agent.grounding.stored_values import StoredValueIndex, learn_same_place
from agent.schemas.grounding_index import (
    ListingCountsByPlaceLink,
    LocationNode,
    NamedColumn,
    StoredValue,
)
from agent.sql.execute import fetch_reference_rows
from agent.sql.listing_sql_fragments import ACTIVE_LISTING_CONDITION
from catalog import load_feature_aliases, load_name_aliases, load_named_value_declarations
from common.logger import get_logger
from config import ActiveConfig

logger = get_logger("agent.grounding")

# A declared column with more distinct names than this keeps only its most used ones.
MAX_NAMES_PER_COLUMN = 50_000

ReferenceReader = Callable[[str], list[dict]]


@dataclass(frozen=True)
class GroundingIndex:
    places: PlaceDirectory
    stored: StoredValueIndex
    loaded_at: float
    features: FeatureVocabulary = field(default_factory=FeatureVocabulary)


def load_grounding_index(read: ReferenceReader, *, region: str) -> GroundingIndex:

    aliases = load_name_aliases()
    places = build_place_directory(
        _fetch_v2_nodes(read),
        _fetch_legacy_nodes(read),
        _listing_links(read),
        region=region,
        aliases=aliases,
        inside_outline=_legacy_inside_outlines(read),
    )
    columns = [NamedColumn(**declared) for declared in load_named_value_declarations()]
    kinds = {(column.table, column.column): column.kind for column in columns}
    values: list[StoredValue] = []
    same_place: dict = {}
    for column in columns:
        try:
            values.extend(_fetch_stored_values(read, column))
            if column.same_place_as:
                canonical_kind = kinds.get((column.table, column.same_place_as), "area")
                same_place.update(
                    learn_same_place(column, canonical_kind, _fetch_same_place_pair_counts(read, column))
                )
        except Exception as exc:
            # One broken declaration must not take grounding down for every other column.
            logger.warning(
                "grounding.column_failed",
                extra={
                    "extra_data": {
                        "table": column.table,
                        "column": column.column,
                        "error": str(exc)[:200],
                    }
                },
            )
    stored = StoredValueIndex(values, same_place, aliases)
    features = build_feature_vocabulary(_fetch_features(read), load_feature_aliases())
    logger.info(
        "grounding.loaded",
        extra={
            "extra_data": {
                "places": len(places),
                "stored_values": len(stored),
                "same_place": len(same_place),
                "features": len(features.features),
            }
        },
    )
    return GroundingIndex(places=places, stored=stored, loaded_at=time.monotonic(), features=features)


class GroundingCache:
    """Serves the last loaded index and reloads it in the background once it is older than `max_age`."""

    def __init__(
        self, loader: Callable[[], GroundingIndex], max_age_seconds: float
    ) -> None:
        self._loader = loader
        self._max_age = max_age_seconds
        self._index: GroundingIndex | None = None
        self._lock = threading.Lock()
        self._loading = False
        self._first_attempt_done = threading.Event()

    def get(self) -> GroundingIndex | None:
        """The current index, or None while the first load is still running. Never blocks."""
        index = self._index
        if index is None or time.monotonic() - index.loaded_at > self._max_age:
            self.load_in_background()
        return index

    def wait_for_first_load(self, timeout_seconds: float) -> GroundingIndex | None:
        """The index, waiting up to `timeout_seconds` for the first load to finish. Starts one
        if none is running. Returns None when the first load failed or is still running."""
        index = self.get()
        if index is None:
            self._first_attempt_done.wait(timeout_seconds)
            index = self._index
        return index

    def load_in_background(self) -> None:
        with self._lock:
            if self._loading:
                return
            self._loading = True
        threading.Thread(
            target=self.load_now, name="grounding-load", daemon=True
        ).start()

    def load_now(self) -> GroundingIndex | None:
        """Load on the calling thread. For startup warm-up, scripts, and evals."""
        try:
            self._index = self._loader()
        except Exception:
            # The previous copy, if any, keeps serving. The next request starts another try.
            logger.warning("grounding.load_failed", exc_info=True)
        finally:
            with self._lock:
                self._loading = False
            self._first_attempt_done.set()
        return self._index


_cache: GroundingCache | None = None
_cache_lock = threading.Lock()


def get_grounding_cache() -> GroundingCache:
    """Process-wide cache over the warehouse."""
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = GroundingCache(
                lambda: load_grounding_index(
                    fetch_reference_rows, region=ActiveConfig.GROUNDING_REGION
                ),
                max_age_seconds=ActiveConfig.GROUNDING_REFRESH_SECONDS,
            )
        return _cache


def _fetch_features(read: ReferenceReader) -> list[Feature]:
    """Amenity and view titles that at least one listing carries."""
    rows = read(
        "SELECT 'amenity' AS kind, a.id, a.title_en FROM public.amenities a "
        "WHERE EXISTS (SELECT 1 FROM public.amenity_property ap WHERE ap.amenity_id = a.id) "
        "UNION ALL "
        "SELECT 'view' AS kind, v.id, v.title_en FROM public.views v "
        "WHERE EXISTS (SELECT 1 FROM public.property_view pv WHERE pv.view_id = v.id)"
    )
    return [
        Feature(kind=FeatureKind(row["kind"]), id=int(row["id"]), title=str(row["title_en"]).strip())
        for row in rows
        if row.get("id") is not None and str(row.get("title_en") or "").strip()
    ]


def _fetch_v2_nodes(read: ReferenceReader) -> list[LocationNode]:
    rows = read(
        "SELECT id, parent_id, type, title_en, aliases_en, lat, lng "
        "FROM public.locations_v2 WHERE title_en IS NOT NULL"
    )
    return [
        LocationNode(
            id=int(row["id"]),
            parent_id=_optional_int(row["parent_id"]),
            title=str(row["title_en"]),
            breadth=V2_BREADTH.get(str(row["type"] or "").lower(), Breadth.PROJECT),
            aliases=_leading_alias_parts(row["aliases_en"]),
            lat=_optional_float(row["lat"]),
            lng=_optional_float(row["lng"]),
        )
        for row in rows
    ]


def _fetch_legacy_nodes(read: ReferenceReader) -> list[LocationNode]:
    rows = read(
        "SELECT id, parent_id, type, name_en, lat, lng FROM public.locations WHERE name_en IS NOT NULL"
    )
    return [
        LocationNode(
            id=int(row["id"]),
            parent_id=_optional_int(row["parent_id"]),
            title=str(row["name_en"]),
            breadth=LEGACY_BREADTH.get(str(row["type"] or "").lower(), Breadth.PROJECT),
            lat=_optional_float(row["lat"]),
            lng=_optional_float(row["lng"]),
        )
        for row in rows
    ]


def _legacy_inside_outlines(read: ReferenceReader) -> dict[int, list[int]]:
    """v2 areas with a drawn outline, each with the legacy nodes whose point lies inside it.

    Outlines overlap, so a point belongs only to the smallest outline that contains it.
    """
    try:
        rows = read(
            "SELECT DISTINCT ON (node.id) area.id AS area_id, node.id AS legacy_id "
            "FROM public.locations_v2 area "
            "JOIN public.locations node ON node.lat IS NOT NULL AND node.lng IS NOT NULL "
            "AND ST_Contains(area.geom, "
            "ST_SetSRID(ST_MakePoint(node.lng::float8, node.lat::float8), ST_SRID(area.geom))) "
            "WHERE area.geom IS NOT NULL "
            "ORDER BY node.id, ST_Area(area.geom)"
        )
    except Exception:
        # Outlines only sharpen containment; the tree and same-spot links still work without them.
        logger.warning("grounding.outlines_unavailable", exc_info=True)
        return {}
    inside: dict[int, list[int]] = defaultdict(list)
    for row in rows:
        inside[int(row["area_id"])].append(int(row["legacy_id"]))
    return dict(inside)


def _listing_links(read: ReferenceReader) -> ListingCountsByPlaceLink:
    by_v2 = read(
        f"SELECT p.location_v2_id AS id, count(*) AS n FROM public.properties p "
        f"WHERE {ACTIVE_LISTING_CONDITION} AND p.location_v2_id IS NOT NULL GROUP BY 1"
    )
    by_legacy = read(
        f"SELECT linked.id, count(*) AS n FROM public.properties p, "
        f"unnest(ARRAY[p.location_master_project_id, p.location_project_id, p.location_building_id]) AS linked(id) "
        f"WHERE {ACTIVE_LISTING_CONDITION} AND linked.id IS NOT NULL GROUP BY 1"
    )
    by_address = read(
        f"SELECT trim(part) AS part, count(*) AS n FROM public.properties p, "
        f"unnest(string_to_array(lower(p.address_en), ',')) AS part "
        f"WHERE {ACTIVE_LISTING_CONDITION} GROUP BY 1"
    )
    return ListingCountsByPlaceLink(
        by_v2_id={int(row["id"]): int(row["n"]) for row in by_v2},
        by_legacy_id={int(row["id"]): int(row["n"]) for row in by_legacy},
        by_address_part={
            str(row["part"]): int(row["n"]) for row in by_address if row["part"]
        },
    )


def _fetch_stored_values(read: ReferenceReader, column: NamedColumn) -> list[StoredValue]:
    statement = sql.SQL(
        "SELECT {col}::text AS value, count(*) AS n FROM {table} WHERE {col} IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT {limit}"
    ).format(
        col=sql.Identifier(column.column),
        table=_table_identifier(column.table),
        limit=sql.Literal(MAX_NAMES_PER_COLUMN),
    )
    return [
        StoredValue(
            table=column.table,
            column=column.column,
            value=text,
            kind=column.kind,
            row_count=int(row["n"]),
        )
        for row in read(statement.as_string())
        if (text := str(row["value"]).strip())
    ]


def _fetch_same_place_pair_counts(
    read: ReferenceReader, column: NamedColumn
) -> list[tuple[str, str, int]]:
    statement = sql.SQL(
        "SELECT {name}::text AS name, {canonical}::text AS canonical, count(*) AS n FROM {table} "
        "WHERE {name} IS NOT NULL AND {canonical} IS NOT NULL GROUP BY 1, 2"
    ).format(
        name=sql.Identifier(column.column),
        canonical=sql.Identifier(column.same_place_as or ""),
        table=_table_identifier(column.table),
    )
    return [
        (str(row["name"]).strip(), str(row["canonical"]).strip(), int(row["n"]))
        for row in read(statement.as_string())
    ]


def _table_identifier(qualified: str) -> sql.Identifier:
    return sql.Identifier(*qualified.split(".", 1))


def _leading_alias_parts(aliases) -> tuple[str, ...]:
    """v2 aliases read "Dubai Marina, Dubai, UAE". The part before the first comma is the name."""
    if not isinstance(aliases, list):
        return ()
    parts = (
        str(alias).split(",", 1)[0].strip()
        for alias in aliases
        if isinstance(alias, str)
    )
    return tuple(part for part in parts if part)


def _optional_int(value) -> int | None:
    return None if value is None else int(value)


def _optional_float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
