"""Listing cards by id: one fixed statement, shaped for the UI and for the answer model."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from agent.sql.execute import run_against_warehouse
from common.logger import get_logger

logger = get_logger("agent.sql")

CARD_IMAGE_LIMIT = 6
# The answer model reads facts for the first few cards only. The UI still gets every card.
PROMPT_LISTING_LIMIT = 10

# Laravel morph names. The second spelling came from an import that dropped the backslashes.
_PROPERTY_FILE_TYPES = ["App\\Models\\Property", "AppModelsProperty"]
_USER_FILE_TYPE = "App\\Models\\User"

LISTING_CARDS_SQL = """
WITH wanted AS (
    SELECT id, ord FROM unnest(%(ids)s::bigint[]) WITH ORDINALITY AS w(id, ord)
)
SELECT
    p.id,
    p.title_en,
    p.slug_en,
    p.purpose,
    p.show_price,
    p.price_min,
    p.price_max,
    p.yearly_price,
    p.monthly_price,
    p.weekly_price,
    p.daily_price,
    p.rental_period,
    p.rooms,
    p.baths,
    p.area,
    p.completion_status,
    p.furnished,
    p.developer,
    p.is_distress,
    p.address_en,
    p.created_at,
    building.name_en AS building_name,
    project.name_en AS project_name,
    master.name_en AS master_project_name,
    category.name_en AS type,
    NULLIF(TRIM(agency.company_name), '') AS agency_company,
    NULLIF(TRIM(agency.name_en), '') AS agency_user_name,
    NULLIF(TRIM(CONCAT_WS(' ', agent.name_en, agent.surname_en)), '') AS agent_name,
    agency_logo.url AS agency_logo_url,
    agent_photo.url AS agent_image_url,
    photos.urls AS images
FROM wanted w
JOIN public.properties p ON p.id = w.id AND p.deleted_at IS NULL
LEFT JOIN public.locations building ON building.id = p.location_building_id
LEFT JOIN public.locations project ON project.id = p.location_project_id
LEFT JOIN public.locations master ON master.id = p.location_master_project_id
LEFT JOIN public.users agency ON agency.id = p.agency_id
LEFT JOIN public.users agent ON agent.id = p.user_id
LEFT JOIN LATERAL (
    SELECT c.name_en
    FROM public.category_property cp
    JOIN public.categories c ON c.id = cp.category_id
    WHERE cp.property_id = p.id
    ORDER BY (c.category_id IS NULL), c.id
    LIMIT 1
) category ON true
LEFT JOIN LATERAL (
    SELECT array_agg(f.url ORDER BY f.rank) AS urls
    FROM (
        SELECT
            COALESCE(NULLIF(file.cloudfront_url, ''), file.full_path) AS url,
            row_number() OVER (
                ORDER BY file.is_featured DESC NULLS LAST, file.sort_order NULLS LAST, file.id
            ) AS rank
        FROM public.files file
        WHERE file.fileable_id = p.id
          AND file.fileable_type = ANY(%(property_file_types)s::text[])
          AND file.type = 'image'
          AND COALESCE(file.viewable, true)
    ) f
    WHERE f.url IS NOT NULL AND f.rank <= %(image_limit)s
) photos ON true
LEFT JOIN LATERAL (
    SELECT COALESCE(NULLIF(file.cloudfront_url, ''), file.full_path) AS url
    FROM public.files file
    WHERE file.fileable_id = p.agency_id
      AND file.fileable_type = %(user_file_type)s
      AND file.type = 'image'
      AND file.extra_type = 'logo'
    ORDER BY file.id DESC
    LIMIT 1
) agency_logo ON true
LEFT JOIN LATERAL (
    SELECT COALESCE(NULLIF(file.cloudfront_url, ''), file.full_path) AS url
    FROM public.files file
    WHERE file.fileable_id = p.user_id
      AND file.fileable_type = %(user_file_type)s
      AND file.type = 'image'
      AND file.extra_type = 'profile_image'
    ORDER BY file.id DESC
    LIMIT 1
) agent_photo ON true
ORDER BY w.ord
"""

_PRICE_FIELDS = (
    "price_min",
    "price_max",
    "yearly_price",
    "monthly_price",
    "weekly_price",
    "daily_price",
)


class ListingLoader(Protocol):
    """Returns one warehouse row per listing id it found. Tests pass a fake."""

    def __call__(self, ids: list[int]) -> list[dict[str, Any]]: ...


def fetch_listing_card_rows(ids: list[int]) -> list[dict[str, Any]]:
    page = run_against_warehouse(
        LISTING_CARDS_SQL,
        {
            "ids": ids,
            "property_file_types": _PROPERTY_FILE_TYPES,
            "user_file_type": _USER_FILE_TYPE,
            "image_limit": CARD_IMAGE_LIMIT,
        },
    )
    return page.rows


def fetch_listing_cards(ids: list[str], loader: ListingLoader) -> list[dict[str, Any]]:
    """One card per id, in id order. An id the loader cannot fill keeps an id-only card."""
    numeric = [int(item) for item in ids if item.isdigit()]
    rows: list[dict[str, Any]] = []
    if numeric:
        try:
            rows = list(loader(numeric) or [])
        except Exception:
            logger.warning("listing.cards failed", exc_info=True)
    by_id = {str(row.get("id")): _card(row) for row in rows if row.get("id") is not None}
    return [by_id.get(item) or {"id": item} for item in ids]


def listing_display_name(card: dict[str, Any]) -> str:
    """How a listing is named on its own: its building, else its project, else its advert title."""
    return str(card.get("building_name") or card.get("project_name") or card.get("title_en") or "This listing")


def prompt_listing_facts(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the answer model may cite. No photos, links, contact details, or ids: the cards show
    each listing, and a reply that reads ids out is noise to the user."""
    facts: list[dict[str, Any]] = []
    for card in cards[:PROMPT_LISTING_LIMIT]:
        fact = {
            "title": card.get("title_en"),
            "type": card.get("type"),
            "bedrooms": card.get("rooms"),
            "bathrooms": card.get("baths"),
            "size_sqft": to_json_number(card.get("area")),
            "purpose": card.get("purpose"),
            "asking_price_aed": to_json_number(card.get("price_min")),
            "asking_price_max_aed": to_json_number(card.get("price_max")),
            "rent_aed": _rent(card),
            "completion": card.get("completion_status"),
            "furnished": card.get("furnished"),
            "building": card.get("building_name"),
            "project": card.get("project_name"),
            "community": card.get("master_project_name"),
            "address": card.get("address"),
            "developer": card.get("developer"),
            "agency": card.get("agency_name"),
        }
        facts.append({key: value for key, value in fact.items() if value not in (None, "", [])})
    return facts


def _card(row: dict[str, Any]) -> dict[str, Any]:
    images = [str(url) for url in (row.get("images") or []) if url]
    card: dict[str, Any] = {
        "id": str(row["id"]),
        "title_en": row.get("title_en"),
        "slug": row.get("slug_en"),
        "purpose": row.get("purpose"),
        "rental_period": row.get("rental_period"),
        "rooms": row.get("rooms"),
        "baths": row.get("baths"),
        "area": row.get("area"),
        "completion_status": row.get("completion_status"),
        "furnished": row.get("furnished"),
        "type": row.get("type"),
        "building_name": row.get("building_name"),
        "project_name": row.get("project_name"),
        "master_project_name": row.get("master_project_name"),
        "address": row.get("address_en"),
        "developer": row.get("developer"),
        "is_distress": bool(row.get("is_distress")),
        "created_at": row.get("created_at"),
        "images": images,
        "image_url": images[0] if images else None,
        "agency_name": row.get("agency_company") or row.get("agency_user_name"),
        "agency_logo_url": row.get("agency_logo_url"),
        "agent_name": row.get("agent_name"),
        "agent_image_url": row.get("agent_image_url"),
    }
    # A listing that hides its price shows "on request", never a stale figure.
    if row.get("show_price") is not False:
        for field in _PRICE_FIELDS:
            card[field] = row.get(field)
    return {key: value for key, value in card.items() if value not in (None, "")}


def _rent(card: dict[str, Any]) -> dict[str, Any] | None:
    if "rent" not in str(card.get("purpose") or ""):
        return None
    period = str(card.get("rental_period") or "yearly")
    amount = to_json_number(card.get(f"{period}_price"))
    if amount is None:
        return None
    return {"amount": amount, "period": period}


def to_json_number(value: Any) -> int | float | None:
    """A stored amount as a JSON number: whole values as int, the rest as float."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    if number == number.to_integral_value():
        return int(number)
    return float(number)
