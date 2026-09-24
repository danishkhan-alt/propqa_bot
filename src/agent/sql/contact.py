"""Who to call about one live listing: the agency when it has a number or email, else the listing agent."""

from __future__ import annotations

from typing import Any, Protocol

CONTACT_SQL = """
SELECT
    p.id AS property_id,
    NULLIF(TRIM(p.contact_name_en), '') AS listing_name,
    NULLIF(TRIM(p.proxy_phone), '') AS listing_proxy_phone,
    NULLIF(TRIM(p.phone), '') AS listing_phone,
    NULLIF(TRIM(p.mobile), '') AS listing_mobile,
    NULLIF(TRIM(p.whatsapp), '') AS listing_whatsapp,
    NULLIF(TRIM(p.email), '') AS listing_email,
    agency.id AS agency_id,
    NULLIF(TRIM(agency.company_name), '') AS agency_company,
    NULLIF(TRIM(agency.name_en), '') AS agency_name,
    NULLIF(TRIM(agency.phone), '') AS agency_phone,
    NULLIF(TRIM(agency.email), '') AS agency_email,
    agency.verification_status AS agency_verification,
    agent.id AS agent_id,
    NULLIF(TRIM(CONCAT_WS(' ', agent.name_en, agent.surname_en)), '') AS agent_name,
    NULLIF(TRIM(agent.phone), '') AS agent_phone,
    NULLIF(TRIM(agent.email), '') AS agent_email,
    agent.verification_status AS agent_verification
FROM public.properties p
LEFT JOIN public.users agency ON agency.id = p.agency_id AND agency.deleted_at IS NULL
LEFT JOIN public.users agent ON agent.id = p.user_id AND agent.deleted_at IS NULL
WHERE p.id = %(property_id)s
  AND p.status = 'active'
  AND p.deleted_at IS NULL
"""


class ContactLoader(Protocol):
    """Returns the contact row for one live listing, or None. Tests pass a fake."""

    def __call__(self, property_id: int) -> dict[str, Any] | None: ...


def load_from_warehouse(property_id: int) -> dict[str, Any] | None:
    from agent.sql.execute import run_against_warehouse

    page = run_against_warehouse(CONTACT_SQL, {"property_id": property_id})
    return page.rows[0] if page.rows else None


def listing_contact(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The shape the UI's contact sheet reads. None when nobody can be reached."""
    if not row:
        return None
    agency_phone = row.get("agency_phone")
    if agency_phone or row.get("agency_email"):
        contact = {
            "agent_id": row.get("agency_id"),
            "agent_name": row.get("agency_company") or row.get("agency_name"),
            "company_name": row.get("agency_company") or row.get("agency_name"),
            "phone": agency_phone,
            "mobile": None,
            "whatsapp": agency_phone,
            "email": row.get("agency_email"),
            "verification_status": row.get("agency_verification") or "unverified",
            "contact_source": "agency",
        }
    else:
        # The listing's own numbers first: a proxy number is how the advertiser tracks calls.
        phone = row.get("listing_proxy_phone") or row.get("listing_phone") or row.get("agent_phone")
        contact = {
            "agent_id": row.get("agent_id"),
            "agent_name": row.get("listing_name") or row.get("agent_name"),
            "company_name": row.get("agency_company") or row.get("agency_name"),
            "phone": phone,
            "mobile": row.get("listing_mobile"),
            "whatsapp": row.get("listing_whatsapp") or row.get("listing_mobile") or phone,
            "email": row.get("listing_email") or row.get("agent_email"),
            "verification_status": row.get("agent_verification") or "unverified",
            "contact_source": "listing_agent",
        }
    if not (contact["phone"] or contact["mobile"] or contact["whatsapp"] or contact["email"]):
        return None
    return {"property_id": int(row["property_id"]), **contact}
