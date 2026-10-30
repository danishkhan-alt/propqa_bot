from __future__ import annotations

import re

from agent.enums.listing import Completion, ListingPurpose, MentionKind
from agent.enums.routing import Intent, Route, TurnKind
from agent.schemas.listing import ListingFilters, NameMention
from agent.schemas.routes import DomainRoute, LastNeedDb, LookupAssumptions, QueryRoute
from agent.sql.handover_window import (
    asks_for_future_project_list,
    asks_for_project_attribute,
    asks_for_ready,
    budget_bounds,
    keeps_shortlist,
    wants_project_listings,
)
from agent.sql.recipes import get_recipe
from catalog import list_domains, load_domain
from common.schemas.pagination import build_page_request
from config import ActiveConfig

MAX_PRIMARY_DOMAINS = 3
MAX_LOADED_DOMAINS = 3
# Row results share one page window. An average or a single lookup does not.
_PAGED_INTENTS = frozenset({Intent.LIST, Intent.RANK})


def sanitize_query_route(
    route: QueryRoute,
    last: LastNeedDb | None,
    message: str = "",
    session_profile: dict | None = None,
) -> tuple[QueryRoute, list[str]]:
    """Structural fixes only. The model's route, purpose, limit, and order stand."""
    notes: list[str] = []
    updated = route

    if _bare_arithmetic(message):
        updated = updated.model_copy(
            update={
                "route": Route.OUT_OF_SCOPE,
                "turn_kind": TurnKind.NEW,
                "intent": Intent.OTHER,
                "rationale": "Arithmetic with no property subject.",
            }
        )
        notes.append("bare_arithmetic")
        return updated, notes

    if updated.turn_kind is TurnKind.REFINE and last is None:
        updated = updated.model_copy(update={"turn_kind": TurnKind.NEW})
        notes.append("refine_without_prior")

    if updated.confidence < 0.7:
        notes.append("low_confidence")

    # The whole city is the scope of every lookup, not a place to filter on. Kept as a name,
    # it matches dozens of stored values ("Dubai Marina", "Dubai Hills") and narrows wrongly.
    region = _region_names()
    kept = [
        name
        for name in updated.names
        if " ".join(name.text.casefold().split()) not in region
    ]
    if len(kept) != len(updated.names):
        updated = updated.model_copy(update={"names": kept})
        notes.append("dropped_region_name")

    updated, shortlist_notes = _keep_project_shortlist(updated, last, message, session_profile)
    notes.extend(shortlist_notes)
    updated, search_notes = _listing_search_for_named_place(updated, message)
    notes.extend(search_notes)
    return updated, notes


def _keep_project_shortlist(
    route: QueryRoute,
    last: LastNeedDb | None,
    message: str,
    session_profile: dict | None,
) -> tuple[QueryRoute, list[str]]:
    """Stay on the projects just shown, or look up listings in them. A new place starts a new search."""
    notes: list[str] = []
    projects = list(((last.result_meta if last is not None else None) or {}).get("projects") or [])
    updated = _timeline_for_launch(route, message)
    if updated.profile.timeline != route.profile.timeline:
        notes.append("timeline_off_plan" if updated.profile.timeline == "off_plan" else "timeline_ready")
    if not keeps_shortlist(message, updated.names, projects):
        return updated, notes
    if wants_project_listings(message, projects):
        bucket = updated.profile.budget_range or (session_profile or {}).get("budget_range")
        low, high = budget_bounds(bucket)
        current = updated.listing_filters or ListingFilters()
        filters = current.model_copy(
            update={
                "purpose": ListingPurpose.SALE,
                "completion": Completion.OFF_PLAN,
                "price_min": low if low is not None else current.price_min,
                "price_max": high if high is not None else current.price_max,
            }
        )
        return (
            updated.model_copy(
                update={
                    "route": Route.NEED_DB,
                    "turn_kind": TurnKind.PIVOT,
                    "intent": Intent.LIST,
                    "listing_filters": filters,
                    "names": [
                        NameMention(text=str(item["name"]), kind=MentionKind.PLACE)
                        for item in projects
                        if item.get("name")
                    ],
                }
            ),
            [*notes, "listing_search_for_shortlist"],
        )
    intent = updated.intent if updated.intent in {Intent.LIST, Intent.RANK, Intent.ASSESS, Intent.COMPARE} else Intent.ASSESS
    names = [
        NameMention(text=str(item["name"]), kind=MentionKind.OTHER)
        for item in projects
        if item.get("name")
    ]
    if asks_for_project_attribute(message):
        intent = Intent.LIST
        known = {" ".join(name.text.casefold().split()) for name in names}
        for place in _places_from_last(last):
            if " ".join(place.text.casefold().split()) not in known:
                names.append(place)
                known.add(" ".join(place.text.casefold().split()))
    return (
        updated.model_copy(
            update={
                "route": Route.NEED_DB,
                "turn_kind": TurnKind.REFINE,
                "intent": intent,
                "listing_filters": None,
                "names": names,
            }
        ),
        [*notes, "kept_project_shortlist"],
    )


def _places_from_last(last: LastNeedDb | None) -> list[NameMention]:
    """Places named on the previous lookup, so 'their developers' stays in that area."""
    raw = ((last.result_meta if last is not None else None) or {}).get("names") or []
    places: list[NameMention] = []
    for item in raw:
        if not isinstance(item, dict) or str(item.get("kind") or "") != MentionKind.PLACE.value:
            continue
        text = " ".join(str(item.get("text") or "").split())
        if text:
            places.append(NameMention(text=text, kind=MentionKind.PLACE))
    return places


def _timeline_for_launch(route: QueryRoute, message: str) -> QueryRoute:
    """A new launch is off-plan. Asking for a ready home records that instead."""
    if route.profile.timeline is not None:
        return route
    if asks_for_ready(message):
        timeline = "ready"
    elif asks_for_future_project_list(message) or "off-plan" in message.casefold() or "off plan" in message.casefold():
        timeline = "off_plan"
    else:
        return route
    return route.model_copy(update={"profile": route.profile.model_copy(update={"timeline": timeline})})


def _region_names() -> set[str]:
    region = ActiveConfig.GROUNDING_REGION.casefold().strip()
    return {
        region,
        f"{region} city",
        f"{region}, uae",
        f"{region} uae",
        f"all of {region}",
        f"all {region}",
    }


_PROPERTY_SUBJECT = re.compile(
    r"\b(?:propert(?:y|ies)|apartments?|villas?|rent|sale|price|aed|dirhams?|mortgage|yield|"
    r"fees?|bedrooms?|listings?|sqft|community|dubai)\b",
    re.IGNORECASE,
)
_ARITHMETIC_PREFIX = re.compile(
    r"^(?:what(?:'s| is)|whats|calculate|compute|how much is)\s+",
    re.IGNORECASE,
)
_SEE_PROPERTIES = re.compile(
    r"\b(?:propert(?:y|ies)|listings?|apartments?|villas?|offices?|flats?|homes?|units?|"
    r"townhouses?|penthouses?)\b",
    re.IGNORECASE,
)
_NOT_A_LISTING_LIST = re.compile(r"\b(?:schools?|metro|tram|bus|transit|stations?)\b", re.IGNORECASE)
_PLACE_COMPARE = re.compile(r"\bcompare\b.+\band\b|\bversus\b|\bvs\.?\b", re.IGNORECASE)


def _bare_arithmetic(message: str) -> bool:
    """True when the message is only a sum, with no property subject."""
    if _PROPERTY_SUBJECT.search(message):
        return False
    text = _ARITHMETIC_PREFIX.sub("", message.strip().rstrip("?.!").strip()).strip()
    if re.search(r"[A-Za-z]", text):
        return False
    return bool(re.fullmatch(r"[\d\s+\-*/x×÷.]+", text)) and bool(re.search(r"\d", text)) and bool(
        re.search(r"[+\-*/x×÷]", text)
    )


def _listing_search_for_named_place(route: QueryRoute, message: str) -> tuple[QueryRoute, list[str]]:
    """A list of properties in a named place uses listing search, which pages and counts.

    An aggregate, a compare, and a schools or transit question stay on the drafted path.
    """
    if route.route is not Route.NEED_DB or route.intent not in {Intent.LIST, Intent.RANK}:
        return route, []
    if route.listing_filters is not None or _NOT_A_LISTING_LIST.search(message):
        return route, []
    if not _SEE_PROPERTIES.search(message):
        return route, []
    if not any(name.kind is MentionKind.PLACE for name in route.names):
        return route, []
    return route.model_copy(update={"listing_filters": ListingFilters()}), ["listing_search_for_place"]


def sanitize_domain_route(route: DomainRoute, message: str = "") -> tuple[DomainRoute, list[str]]:
    """Drop unknown ids and cap how many packs are loaded.

    The only packs added are a chosen recipe's own, and the locations join a transactions compare
    of two places needs when the catalog already declares that join.
    """

    notes: list[str] = []
    known = _catalog_domain_ids()
    primary = _dedupe_known_domain_ids(route.domain_ids, known)
    if any(domain_id not in known for domain_id in route.domain_ids):
        notes.append("dropped_unknown")

    chosen = get_recipe(route.recipe_id)
    if route.recipe_id and chosen is None:
        notes.append("dropped_unknown_recipe")
    if chosen is not None:
        primary = [
            *chosen.domains,
            *(domain_id for domain_id in primary if domain_id not in chosen.domains),
        ]

    joins = [
        domain_id
        for domain_id in _dedupe_known_domain_ids(route.join_ids, known)
        if domain_id not in primary
    ]

    if _restore_locations_join(primary, joins, message, known):
        joins.append("locations")
        notes.append("restored_locations_join")

    if len(primary) > MAX_PRIMARY_DOMAINS:
        primary = primary[:MAX_PRIMARY_DOMAINS]
        notes.append("truncated_primary")

    while len(primary) + len(joins) > MAX_LOADED_DOMAINS:
        if joins:
            joins.pop()
            notes.append("truncated_joins")
        elif primary:
            primary.pop()
            notes.append("truncated_primary")
        else:
            break

    recipe_id = chosen.id if chosen is not None else None
    return (
        route.model_copy(
            update={"domain_ids": primary, "join_ids": joins, "recipe_id": recipe_id}
        ),
        notes,
    )


def _dedupe_known_domain_ids(ids: list[str], known: set[str]) -> list[str]:
    seen: list[str] = []
    for domain_id in ids:
        if domain_id in known and domain_id not in seen:
            seen.append(domain_id)
    return seen


def _catalog_domain_ids() -> set[str]:
    return {str(domain["id"]) for domain in list_domains()}


def _restore_locations_join(primary: list[str], joins: list[str], message: str, known: set[str]) -> bool:
    """A compare of two places on transactions needs the locations pack the catalog already lists."""
    if "locations" not in known or "locations" in primary or "locations" in joins:
        return False
    if "transactions" not in primary or not _PLACE_COMPARE.search(message):
        return False
    return _catalog_declares_join("transactions", "locations")


def _catalog_declares_join(domain_id: str, join_id: str) -> bool:
    try:
        domain = load_domain(domain_id)
    except KeyError:
        return False
    return any(
        isinstance(item, dict) and str(item.get("domain")) == join_id
        for item in domain.get("joins") or []
    )


def build_lookup_assumptions(route: QueryRoute) -> LookupAssumptions:
    """Keep the model's purpose and order. Page a list with the shared window."""
    if route.intent not in _PAGED_INTENTS:
        return LookupAssumptions(purpose=route.purpose, limit=route.limit, order=route.order)
    window = build_page_request(per_page=route.limit)
    return LookupAssumptions(
        purpose=route.purpose,
        limit=window.per_page,
        order=route.order,
        page=window.page,
    )
