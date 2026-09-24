"""The contact sheet reads one listing's contact, agency first."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent.sql.execute import SqlFailed
from app import create_app
from common.cache import MemoryCache, set_cache


@pytest.fixture(autouse=True)
def memory_cache():
    set_cache(MemoryCache())
    yield
    set_cache(None)


def _row(**fields) -> dict:
    return {
        "property_id": 7,
        "listing_name": "Sara",
        "listing_proxy_phone": "+971800111",
        "listing_phone": "+971500000",
        "agency_id": 3,
        "agency_company": "Blue Keys",
        "agency_phone": None,
        "agency_email": None,
        "agent_id": 9,
        "agent_verification": "approved",
        **fields,
    }


def _get(loader, property_id="7"):
    client = TestClient(create_app(contact_loader=loader))
    with client:
        return client.get(f"/api/leads/property-contact?property_id={property_id}")


def test_the_agency_is_the_contact_when_it_can_be_reached():
    response = _get(lambda pid: _row(agency_phone="+97140000", agency_email="hi@bluekeys.ae"))
    assert response.status_code == 200
    contact = response.json()["contact"]
    assert contact["contact_source"] == "agency"
    assert contact["phone"] == "+97140000"
    assert contact["agent_name"] == "Blue Keys"


def test_otherwise_the_listing_agent_with_the_tracked_number():
    contact = _get(lambda pid: _row()).json()["contact"]
    assert contact["contact_source"] == "listing_agent"
    assert contact["phone"] == "+971800111"
    assert contact["agent_name"] == "Sara"
    assert contact["company_name"] == "Blue Keys"


def test_a_listing_nobody_can_answer_is_not_found():
    assert _get(lambda pid: None).status_code == 404
    assert _get(lambda pid: _row(listing_proxy_phone=None, listing_phone=None)).status_code == 404


def test_a_bad_id_is_rejected_and_a_warehouse_error_is_unavailable():
    assert _get(lambda pid: _row(), property_id="0").status_code == 422

    def down(pid):
        raise SqlFailed("timeout")

    assert _get(down).status_code == 500
