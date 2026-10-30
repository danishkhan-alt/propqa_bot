"""Answer a lookup from the warehouse.

Property searches are written in code from the router's filters (`run_listing_lookup`).
Everything else is drafted by the model from the loaded catalog and the grounded names,
run, and retried once (`run_sql_lookup`).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

from langchain_core.runnables import RunnableConfig

from agent.enums.listing import Completion, Furnishing, MentionKind, NearStation
from agent.enums.routing import Intent
from agent.schemas.grounding import Grounding, as_grounding
from agent.schemas.listing import GOLDEN_VISA_MIN_PRICE_AED, ListingFilters
from agent.schemas.listing_search import BrandPlace, ListingSearch
from agent.schemas.recipes import BoundRecipe
from agent.schemas.routes import QueryRoute, as_assumptions, as_domain_route, as_last_need_db, as_query_route
from agent.schemas.sql import SqlDraft, SqlPage
from agent.services.transcript import (
    ANSWER_HISTORY_MESSAGE_LIMIT,
    format_recent_history,
    latest_user_text,
)
from agent.sql.execute import SqlFailed
from agent.grounding import get_grounding_cache
from agent.sql.filter_values import check_filter_values, exclude_rows_outside_region, explain_missing_column
from agent.sql.handover_window import (
    asks_for_project_attribute,
    constrain_offplan_sql,
    drop_past_handovers,
    missing_project_name_error,
    past_rows_error,
    project_search_for,
    select_has_project_name,
)
from agent.sql.guard import (
    SqlRejected,
    applied_conditions,
    blended_average_reasons,
    overall_figure_sql,
    prepare_select,
    referenced_tables,
    segment_rules,
    tables_in_domains,
)
from agent.sql.listing_card_ids import is_listing_list_request, listing_card_ids_from_rows
from agent.sql.listing_search import search_listings
from agent.sql.listing_text_search import build_text_query
from agent.sql.listing_sql_fragments import LISTINGS_TABLE
from agent.sql.recipes import bind_recipe, get_recipe
from agent.sql.trace import trace_sql_attempt
from agent.sql.transit import STATION_KINDS, STATION_LABELS
from agent.states.chat import ChatState
from catalog import get_table_date_coverage
from common.logger import get_logger
from common.schemas.pagination import build_page_request
from config import ActiveConfig

logger = get_logger("agent.sql")

MAX_ATTEMPTS = 2
EMPTY_LOOKUP_REPLY = (
    "I couldn't find anything matching that. Want me to widen the area or the price range?"
)
FAILED_LOOKUP_REPLY = (
    "I couldn't work that out this time. Ask me again, or try one part of it at a time."
)
NO_ROWS_RETRY_REASON = "The query returned no rows."
ALL_ZERO_ROW_RETRY_REASON = (
    "The query returned one row whose values are all zero or empty. A name filter probably matched "
    "nothing; use the stored values in resolved_names, or check the filters against the catalog."
)


def _empty_name_retry(grounding) -> str:
    """The no-rows retry, naming the stored column each resolved place actually uses."""
    shown: list[str] = []
    for name in grounding.names if grounding is not None else []:
        values = [
            f"{match.table}.{match.column} = '{match.value}'"
            for match in name.stored[:6]
        ]
        if values:
            shown.append(f"{name.text}: " + "; ".join(values))
    if not shown:
        return NO_ROWS_RETRY_REASON
    return (
        NO_ROWS_RETRY_REASON
        + " Filter the name with = or IN on a stored value: "
        + " ".join(shown)
    )
BLENDED_AVERAGE_NOTE = "These figures average several kinds of property together, so treat them as a blend."
LISTING_INTENTS = frozenset({Intent.LIST, Intent.RANK, Intent.AGGREGATE})


def uses_listing_search(state: ChatState) -> bool:
    """The user wants properties on the market, including how many match. Written in code.

    The router's listing filters decide this, not which catalog packs were loaded. An aggregate
    without those filters (a sales total, an average) stays on the drafted path.
    """
    query = as_query_route(state.get("query_route"))
    return query is not None and query.listing_filters is not None and query.intent in LISTING_INTENTS


def run_listing_lookup(state: ChatState, runner, *, client=None) -> dict:
    """Search live listings from the router's filters and the grounded names. No model call."""
    query = as_query_route(state.get("query_route"))
    domain = as_domain_route(state.get("domain_route"))
    domain_ids = [*domain.domain_ids, *domain.join_ids] if domain is not None else []
    grounding = as_grounding(state.get("grounding")) or Grounding()
    assumptions = as_assumptions(state.get("assumptions"))
    window = build_page_request(
        page=(assumptions.page if assumptions and assumptions.page else 1),
        per_page=assumptions.limit if assumptions else None,
    )
    search = _build_listing_search(query, grounding)
    try:
        found = search_listings(
            search,
            runner,
            limit=window.per_page,
            offset=(window.page - 1) * window.per_page,
        )
    except SqlFailed as exc:
        if not _can_retry_without_listing_text(search):
            return _failed_listing_lookup(domain_ids, exc, client)
        search = replace(
            search,
            text_query=None,
            text_requirements=[],
            match_features_in_text=False,
            unchecked_requirements=[*search.unchecked_requirements, *search.text_requirements],
        )
        try:
            found = search_listings(
                search,
                runner,
                limit=window.per_page,
                offset=(window.page - 1) * window.per_page,
            )
        except SqlFailed as retry_exc:
            return _failed_listing_lookup(domain_ids, retry_exc, client)
    rows = [{"property_id": listing_id} for listing_id in found.ids]
    last = _build_sql_result(
        domain_ids=domain_ids,
        attempt=1,
        purpose="property search",
        sql=found.query.sql,
        status="rows" if rows else "empty",
        columns=["property_id"],
        rows=rows,
        duration_ms=found.duration_ms,
        error=None if rows else NO_ROWS_RETRY_REASON,
    )
    last.update(
        params=found.query.params,
        total=found.total,
        notes=found.notes,
        filters=_stated_listing_filters(search),
        # The station kinds the ids were found near, after any loosening. Empty when none.
        station_kinds=list(STATION_KINDS.get(found.filters.near_station, ())),
    )
    trace_sql_attempt(last, client)
    _stamp_handover(last, _project_search(state, query, _latest_user_message(state)))
    return {"sql_result": last, "sql_rows": rows, "listing_ids": found.ids}


def run_sql_lookup(
    state: ChatState,
    models,
    runner,
    *,
    config: RunnableConfig | None = None,
    client=None,
    row_cap: int | None = None,
) -> dict:
    """Return `sql_result` and `sql_rows` for the answer node. At most two attempts."""
    domain = as_domain_route(state.get("domain_route"))
    domain_ids = [*domain.domain_ids, *domain.join_ids] if domain is not None else []
    allowed = tables_in_domains(domain_ids)
    cap = ActiveConfig.SQL_ROW_CAP if row_cap is None else row_cap
    assumptions = as_assumptions(state.get("assumptions"))
    frame = _frame_for_prompt(state.get("query_frame"))
    catalog = state.get("catalog_context") or ""
    message = _latest_user_message(state)
    history = _history_summary(state)

    listing_ids_only = is_listing_list_request(state)
    grounding = as_grounding(state.get("grounding"))
    query = as_query_route(state.get("query_route"))
    project_search = _project_search(state, query, message)
    if not listing_ids_only and domain is not None:
        bound = bind_recipe(chosen, grounding) if (chosen := get_recipe(domain.recipe_id)) else None
        if chosen is not None and bound is None:
            logger.info("sql.recipe_unbound", extra={"extra_data": {"recipe": chosen.id}})
        answered_by_recipe = _answer_with_recipe(bound, runner, cap, client) if bound else None
        if answered_by_recipe is not None:
            _stamp_handover(answered_by_recipe["sql_result"], project_search)
            return answered_by_recipe
    resolved_names = grounding.for_sql_prompt() if grounding and grounding.names else None
    typed_names = [name.text for name in query.names] if query is not None else []
    rules = segment_rules(domain_ids)
    previous_error: str | None = None
    last: dict[str, Any] = _undrafted_sql_result(domain_ids)
    # An attempt that returned rows, kept in case the retry it prompted fails outright.
    answered: dict[str, Any] | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        draft = _draft_sql(
            models,
            message=message,
            history=history,
            catalog=catalog,
            allowed_tables=sorted(allowed),
            assumptions=assumptions.model_dump() if assumptions else None,
            query_frame=frame,
            previous_error=previous_error,
            listing_ids_only=listing_ids_only,
            resolved_names=resolved_names,
            handover_window=project_search.window.as_dict() if project_search.window else None,
            shortlist_projects=list(project_search.names),
            starting_price_aed=project_search.price_payload(),
            config=config,
        )
        logger.info(
            "sql.generate",
            extra={
                "extra_data": {
                    "attempt": attempt,
                    "purpose": draft.purpose,
                    "sql": draft.sql,
                    "domain_ids": domain_ids,
                }
            },
        )
        if draft.missing.strip() and not draft.sql.strip():
            # The catalog does not hold it. A retry would only draft a stand-in.
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql="",
                status="unavailable",
                error=draft.missing.strip(),
            )
            trace_sql_attempt(last, client)
            break
        try:
            guarded = prepare_select(draft.sql, allowed, cap)
        except SqlRejected as exc:
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=draft.sql,
                status="failed",
                error=str(exc),
            )
            trace_sql_attempt(last, client)
            previous_error = str(exc)
            continue
        checked = check_filter_values(guarded, grounding, typed_names)
        if checked.corrections or checked.removed:
            logger.info(
                "sql.filter_values_corrected",
                extra={"extra_data": {"corrections": checked.corrections, "removed": checked.removed}},
            )
            guarded = checked.sql
        guarded = overall_figure_sql(guarded, message, rules)
        constrained = constrain_offplan_sql(guarded, project_search)
        if constrained.retry_error:
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=guarded,
                status="failed",
                error=constrained.retry_error,
            )
            trace_sql_attempt(last, client)
            previous_error = constrained.retry_error
            if attempt == MAX_ATTEMPTS:
                break
            continue
        guarded = constrained.sql
        if (
            asks_for_project_attribute(message)
            and project_search.names
            and not select_has_project_name(guarded)
        ):
            previous_error = missing_project_name_error()
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=guarded,
                status="failed",
                error=previous_error,
            )
            trace_sql_attempt(last, client)
            if attempt == MAX_ATTEMPTS:
                break
            continue
        blends = blended_average_reasons(guarded, rules)
        if blends and attempt < MAX_ATTEMPTS:
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=guarded,
                status="failed",
                error=" ".join(blends),
            )
            trace_sql_attempt(last, client)
            previous_error = last["error"]
            continue
        try:
            page = runner(exclude_rows_outside_region(guarded, _rows_outside_region()))
        except SqlFailed as exc:
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=guarded,
                status="failed",
                error=explain_missing_column(str(exc), guarded),
            )
            trace_sql_attempt(last, client)
            previous_error = last["error"]
            continue
        if not isinstance(page, SqlPage):
            page = SqlPage(
                columns=list(getattr(page, "columns", []) or []),
                rows=list(getattr(page, "rows", []) or []),
                truncated=bool(getattr(page, "truncated", False)),
                duration_ms=int(getattr(page, "duration_ms", 0) or 0),
            )
        visible, dropped_past = drop_past_handovers(page.rows, project_search.window)
        if dropped_past and not visible and project_search.window is not None and attempt < MAX_ATTEMPTS:
            previous_error = " ".join([past_rows_error(project_search.window), *checked.problems])
            last = _build_sql_result(
                domain_ids=domain_ids,
                attempt=attempt,
                purpose=draft.purpose,
                sql=guarded,
                status="empty",
                columns=page.columns,
                rows=[],
                truncated=page.truncated,
                duration_ms=page.duration_ms,
                error=previous_error,
            )
            trace_sql_attempt(last, client)
            continue
        status = "rows" if visible else "empty"
        last = _build_sql_result(
            domain_ids=domain_ids,
            attempt=attempt,
            purpose=draft.purpose,
            sql=guarded,
            status=status,
            columns=page.columns,
            rows=visible,
            truncated=page.truncated,
            duration_ms=page.duration_ms,
            error=None if visible else NO_ROWS_RETRY_REASON,
        )
        last["filters"] = applied_conditions(guarded)
        last["coverage"] = get_table_date_coverage(referenced_tables(guarded))
        last["notes"] = [BLENDED_AVERAGE_NOTE] if blends else []
        trace_sql_attempt(last, client)
        if visible:
            answered = last
        retry_reason = NO_ROWS_RETRY_REASON if not visible else ALL_ZERO_ROW_RETRY_REASON if _is_single_all_zero_row(visible) else None
        if retry_reason == NO_ROWS_RETRY_REASON:
            retry_reason = _empty_name_retry(grounding)
        if retry_reason is None or attempt == MAX_ATTEMPTS:
            break
        previous_error = " ".join([retry_reason, *checked.problems])

    if last["status"] == "failed" and answered is not None:
        last = answered
    _stamp_handover(last, project_search)
    rows = list(last["rows"]) if last["status"] == "rows" else []
    return {
        "sql_result": last,
        "sql_rows": rows,
        "listing_ids": listing_card_ids_from_rows(state, rows, last["sql"] if rows else ""),
    }


def _answer_with_recipe(bound: BoundRecipe, runner, cap: int, client) -> dict | None:
    """The update for a recipe that returned rows, or None so the turn drafts SQL instead."""
    domain_ids = list(bound.recipe.domains)
    try:
        guarded = prepare_select(bound.sql, tables_in_domains(domain_ids), cap)
        page = runner(guarded)
    except (SqlRejected, SqlFailed) as exc:
        logger.warning("sql.recipe_failed", extra={"extra_data": {"recipe": bound.recipe.id, "error": str(exc)}})
        return None
    if not page.rows or _is_single_all_zero_row(page.rows):
        logger.info("sql.recipe_empty", extra={"extra_data": {"recipe": bound.recipe.id}})
        return None
    last = _build_sql_result(
        domain_ids=domain_ids,
        attempt=1,
        purpose=bound.recipe.purpose,
        sql=guarded,
        status="rows",
        columns=page.columns,
        rows=page.rows,
        truncated=page.truncated,
        duration_ms=page.duration_ms,
    )
    last.update(
        recipe=bound.recipe.id,
        filters=bound.filters(),
        coverage=get_table_date_coverage(referenced_tables(guarded)),
        notes=[],
    )
    logger.info(
        "sql.recipe",
        extra={"extra_data": {"recipe": bound.recipe.id, "values": bound.values, "row_count": len(page.rows)}},
    )
    trace_sql_attempt(last, client)
    return {"sql_result": last, "sql_rows": list(page.rows), "listing_ids": []}


def _build_listing_search(query: QueryRoute | None, grounding: Grounding) -> ListingSearch:
    filters = (query.listing_filters if query is not None else None) or ListingFilters()
    places = []
    unmatched_places = []
    brand_places = []
    developers: list[str] = []
    developer_patterns: list[str] = []
    agency_ids: list[int] = []
    agency_names: list[str] = []
    agency_patterns: list[str] = []
    agent_ids: list[int] = []
    agent_names: list[str] = []
    agent_patterns: list[str] = []
    for name in grounding.names:
        developer_values = [
            match.value
            for match in name.stored
            if match.table == LISTINGS_TABLE and match.kind == "developer"
        ]
        if name.kind is MentionKind.PLACE and name.place is not None and developer_values:
            brand_places.append(BrandPlace(place=name.place, developers=developer_values))
            continue
        if name.kind is MentionKind.PLACE and name.place is not None:
            places.append(name.place)
            continue
        if name.kind is MentionKind.PLACE:
            if developer_values:
                developers.extend(developer_values)
            elif name.agency_ids:
                _add_entity(agency_ids, agency_names, name.agency_ids, name.entity_titles, name.text)
            elif name.agent_ids:
                _add_entity(agent_ids, agent_names, name.agent_ids, name.entity_titles, name.text)
            else:
                unmatched_places.append(name.text)
            continue
        if name.kind is MentionKind.DEVELOPER:
            if developer_values:
                developers.extend(developer_values)
            else:
                developer_patterns.append(name.text)
            continue
        if name.kind is MentionKind.AGENCY:
            if name.agency_ids:
                _add_entity(agency_ids, agency_names, name.agency_ids, name.entity_titles, name.text)
            else:
                agency_patterns.append(name.text)
                agency_names.append(name.text)
            continue
        if name.kind is MentionKind.AGENT:
            if name.agent_ids:
                _add_entity(agent_ids, agent_names, name.agent_ids, name.entity_titles, name.text)
            else:
                agent_patterns.append(name.text)
                agent_names.append(name.text)
            continue
        if developer_values:
            developers.extend(developer_values)
        elif name.agency_ids:
            _add_entity(agency_ids, agency_names, name.agency_ids, name.entity_titles, name.text)
        elif name.agent_ids:
            _add_entity(agent_ids, agent_names, name.agent_ids, name.entity_titles, name.text)
    unresolved = [feature.text for feature in grounding.features if not feature.is_resolved]
    text_requirements = [text for text in unresolved if build_text_query([text])]
    text_query = build_text_query(text_requirements) if ActiveConfig.LISTING_TEXT_SEARCH_ENABLED else None
    if not text_query:
        text_requirements = []
    return ListingSearch(
        filters=filters,
        places=places,
        developers=_unique(developers),
        developer_patterns=_unique(developer_patterns),
        unmatched_places=unmatched_places,
        agency_ids=_unique(agency_ids),
        agency_names=_unique(agency_names),
        agency_patterns=_unique(agency_patterns),
        agent_ids=_unique(agent_ids),
        agent_names=_unique(agent_names),
        agent_patterns=_unique(agent_patterns),
        brand_places=brand_places,
        features=[feature for feature in grounding.features if feature.is_resolved],
        any_feature=filters.any_requirement,
        unchecked_requirements=[text for text in unresolved if text not in text_requirements],
        text_requirements=text_requirements,
        text_query=text_query,
        match_features_in_text=bool(ActiveConfig.LISTING_TEXT_SEARCH_ENABLED),
    )


def _add_entity(ids: list[int], names: list[str], matched_ids: list[int], titles: list[str], fallback: str) -> None:
    ids.extend(matched_ids)
    names.extend(titles or [fallback])


def _unique(items: list) -> list:
    return list(dict.fromkeys(items))


def _can_retry_without_listing_text(search: ListingSearch) -> bool:
    """A text-search failure may drop the text match only when other filters still bound it.

    Purpose alone does not count: that would return every listing for sale or rent.
    """
    if not search.text_query and not search.match_features_in_text:
        return False
    filters = search.filters
    return bool(
        filters.property_types
        or filters.bedrooms_min is not None
        or filters.bedrooms_max is not None
        or filters.price_min is not None
        or filters.price_max is not None
        or filters.size_min_sqft is not None
        or filters.size_max_sqft is not None
        or filters.furnishing is not Furnishing.ANY
        or filters.completion is not Completion.ANY
        or filters.near_station is not NearStation.ANY
        or filters.golden_visa
        or search.places
        or search.unmatched_places
        or search.developers
        or search.developer_patterns
        or search.agency_ids
        or search.agency_patterns
        or search.agent_ids
        or search.agent_patterns
        or search.brand_places
        or filters.verified_agent
        or search.features
    )


def _failed_listing_lookup(domain_ids: list[str], exc: SqlFailed, client) -> dict:
    last = _build_sql_result(
        domain_ids=domain_ids,
        attempt=1,
        purpose="property search",
        sql="",
        status="failed",
        error=str(exc),
    )
    trace_sql_attempt(last, client)
    return {"sql_result": last, "sql_rows": [], "listing_ids": []}


def _stated_listing_filters(search: ListingSearch) -> list[str]:
    """The user's own listing filters, as `field: value`, for the reply to name."""
    stated = search.filters.model_dump(
        mode="json",
        exclude_defaults=True,
        exclude={
            "near_station",
            "station_within_km",
            "golden_visa",
            "verified_agent",
            "requirements",
            "any_requirement",
        },
    )
    conditions = [f"{field}: {value}" for field, value in stated.items() if value not in (None, [], "")]
    if search.filters.golden_visa:
        conditions.append(
            f"qualifies for the UAE Golden Visa: for sale at AED {GOLDEN_VISA_MIN_PRICE_AED:,} or more"
        )
    if search.filters.verified_agent:
        conditions.append("verified agent")
    if search.filters.near_station is not NearStation.ANY:
        conditions.append(
            f"within {search.filters.station_km:g} km of {STATION_LABELS[search.filters.near_station]}"
        )
    conditions.extend(f"place: {place.title}" for place in search.places)
    conditions.extend(f"place: {text}" for text in search.unmatched_places)
    conditions.extend(f"developer: {name}" for name in search.developers)
    conditions.extend(f"developer: {name}" for name in search.developer_patterns)
    conditions.extend(f"agency: {name}" for name in search.agency_names)
    conditions.extend(f"agent: {name}" for name in search.agent_names)
    for brand in search.brand_places:
        developer_names = " or ".join(brand.developers)
        conditions.append(f"place or developer: {brand.place.title} or {developer_names}")
    if search.features:
        label = "has any of" if search.any_feature and len(search.features) > 1 else "has"
        wanted = [" or ".join(feature.titles) for feature in search.features]
        conditions.append(f"{label}: " + "; ".join(wanted))
    if search.text_requirements:
        conditions.append("listing text mentions: " + "; ".join(search.text_requirements))
    return conditions


def _rows_outside_region() -> dict[str, tuple[str, frozenset[int]]]:
    index = get_grounding_cache().get()
    return index.outside_region if index is not None else {}


def _is_single_all_zero_row(rows: list[dict]) -> bool:
    """One row of nothing but zeros and nulls: an aggregate whose filter matched no rows."""
    if len(rows) != 1 or not rows[0]:
        return False
    return all(_is_zero_or_empty(value) for value in rows[0].values())


def _is_zero_or_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return False


def _project_search(state: ChatState, query: QueryRoute | None, message: str):
    """The future-launch window and shortlist carried into this lookup."""
    last = as_last_need_db(state.get("last_need_db"))
    profile = state.get("session_profile") or {}
    timeline = profile.get("timeline")
    bucket = profile.get("budget_range")
    stated_budget = False
    if query is not None:
        if query.profile.timeline:
            timeline = query.profile.timeline
        if query.profile.budget_range:
            bucket = query.profile.budget_range
            stated_budget = True
    return project_search_for(
        message,
        carried=last.result_meta if last is not None else None,
        timeline=timeline,
        budget_bucket=bucket,
        route_names=list(query.names) if query is not None else [],
        stated_budget=stated_budget,
    )


def _stamp_handover(result: dict[str, Any], search) -> None:
    """Remember the window for the next turn, or clear it when they ask for a ready home."""
    if search.clear_window:
        result["clear_handover_window"] = True
        result.pop("handover_window", None)
        return
    if search.window is not None:
        result["handover_window"] = search.window.as_dict()


def _draft_sql(models, **kwargs) -> SqlDraft:
    parsed = models.draft_sql(**kwargs)
    if isinstance(parsed, SqlDraft):
        return parsed
    return SqlDraft.model_validate(parsed)


def _frame_for_prompt(frame: dict | None) -> dict | None:
    if not frame:
        return None
    safe = {key: value for key, value in frame.items() if key != "sql"}
    return safe or None


def _latest_user_message(state: ChatState) -> str:
    return latest_user_text(state.get("messages") or [])


def _history_summary(state: ChatState) -> str:
    return format_recent_history(state.get("messages") or [], limit=ANSWER_HISTORY_MESSAGE_LIMIT)


def _undrafted_sql_result(domain_ids: list[str]) -> dict[str, Any]:
    return _build_sql_result(domain_ids=domain_ids, attempt=0, purpose="", sql="", status="failed", error="SQL was not drafted")


def _build_sql_result(
    *,
    domain_ids: list[str],
    attempt: int,
    purpose: str,
    sql: str,
    status: str,
    columns: list[str] | None = None,
    rows: list[dict] | None = None,
    truncated: bool = False,
    duration_ms: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    visible = list(rows or [])
    return {
        "status": status,
        "purpose": purpose,
        "sql": sql,
        "domain_ids": list(domain_ids),
        "attempt": attempt,
        "columns": list(columns or []),
        "rows": visible,
        "row_count": len(visible),
        "truncated": truncated,
        "duration_ms": duration_ms,
        "error": error,
    }
