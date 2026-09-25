from __future__ import annotations

from agent.enums.routing import TurnKind
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute

MAX_PRIMARY = 3
MAX_TOTAL = 3


def apply_query_policy(
    route: QueryRoute,
    last: LastNeedDb | None,
) -> tuple[QueryRoute, list[str]]:
    """Structural fixes only. The model's route, purpose, limit, and order stand."""
    notes: list[str] = []
    updated = route

    if updated.turn_kind is TurnKind.REFINE and last is None:
        updated = updated.model_copy(update={"turn_kind": TurnKind.NEW})
        notes.append("refine_without_prior")

    if updated.confidence < 0.7:
        notes.append("low_confidence")

    # The whole city is the scope of every lookup, not a place to filter on. Kept as a name,
    # it matches dozens of stored values ("Dubai Marina", "Dubai Hills") and narrows wrongly.
    region = _region_names()
    kept = [name for name in updated.names if " ".join(name.text.casefold().split()) not in region]
    if len(kept) != len(updated.names):
        updated = updated.model_copy(update={"names": kept})
        notes.append("dropped_region_name")

    return updated, notes


def _region_names() -> set[str]:
    from config import ActiveConfig

    region = ActiveConfig.GROUNDING_REGION.casefold().strip()
    return {region, f"{region} city", f"{region}, uae", f"{region} uae", f"all of {region}", f"all {region}"}


def sanitize_domain_route(route: DomainRoute) -> tuple[DomainRoute, list[str]]:
    """Drop unknown ids and cap how many packs are loaded.

    The only pack added is a chosen recipe's own, since its tables must be loaded to run it.
    """
    from agent.sql.recipes import recipe

    notes: list[str] = []
    known = _known_ids()
    primary = _unique_known(route.domain_ids, known)
    if any(domain_id not in known for domain_id in route.domain_ids):
        notes.append("dropped_unknown")

    chosen = recipe(route.recipe_id)
    if route.recipe_id and chosen is None:
        notes.append("dropped_unknown_recipe")
    if chosen is not None:
        primary = [*chosen.domains, *(domain_id for domain_id in primary if domain_id not in chosen.domains)]

    joins = [domain_id for domain_id in _unique_known(route.join_ids, known) if domain_id not in primary]

    if len(primary) > MAX_PRIMARY:
        primary = primary[:MAX_PRIMARY]
        notes.append("truncated_primary")

    while len(primary) + len(joins) > MAX_TOTAL:
        if joins:
            joins.pop()
            notes.append("truncated_joins")
        elif primary:
            primary.pop()
            notes.append("truncated_primary")
        else:
            break

    recipe_id = chosen.id if chosen is not None else None
    return route.model_copy(update={"domain_ids": primary, "join_ids": joins, "recipe_id": recipe_id}), notes


def _unique_known(ids: list[str], known: set[str]) -> list[str]:
    seen: list[str] = []
    for domain_id in ids:
        if domain_id in known and domain_id not in seen:
            seen.append(domain_id)
    return seen


def _known_ids() -> set[str]:
    from catalog import list_domains

    return {str(domain["id"]) for domain in list_domains()}
