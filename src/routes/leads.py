"""Listing contact for the property cards' Call and WhatsApp buttons."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from agent.sql.contact import contact_sheet_from_row, fetch_listing_contact_row
from agent.sql.execute import SqlFailed
from common.errors import DatabaseFailure, ResourceNotFound
from common.logger import get_logger

logger = get_logger("leads")
router = APIRouter()


@router.get("/leads/property-contact")
def property_contact(request: Request, property_id: int = Query(gt=0)) -> dict:
    loader = getattr(request.app.state, "contact_loader", None) or fetch_listing_contact_row
    try:
        contact = contact_sheet_from_row(loader(property_id))
    except SqlFailed as exc:
        logger.warning("leads.property_contact failed", exc_info=True)
        raise DatabaseFailure("Contact details are unavailable right now.") from exc
    if contact is None:
        raise ResourceNotFound("No contact available for this listing.")
    return {"contact": contact}
