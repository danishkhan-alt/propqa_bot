"""Listing contact for the property cards' Call and WhatsApp buttons."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from agent.sql.contact import listing_contact, load_from_warehouse
from agent.sql.execute import SqlFailed
from common.errors import DatabaseFailure, ResourceNotFound
from common.logger import get_logger

logger = get_logger("leads")
router = APIRouter()


@router.get("/leads/property-contact")
def property_contact(request: Request, property_id: int = Query(gt=0)) -> dict:
    loader = getattr(request.app.state, "contact_loader", None) or load_from_warehouse
    try:
        contact = listing_contact(loader(property_id))
    except SqlFailed as exc:
        logger.warning("leads.property_contact failed", exc_info=True)
        raise DatabaseFailure("Contact details are unavailable right now.") from exc
    if contact is None:
        raise ResourceNotFound("No contact available for this listing.")
    return {"contact": contact}
