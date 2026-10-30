"""Check that a listing reply's concrete claims are supported by the fact sheet."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.services.llm.calls import invoke_structured_with_fallback
from agent.services.llm.output_schema import build_strict_output_schema
from agent.services.llm.providers import build_chat_models, constrained_output_options
from evals.listing_score import judge_fields

_SYSTEM = """You check a property-search reply against the listings that were returned.

You are given the user's words, the filters the search applied, notes about any filter that was dropped, a fact sheet of the returned listings, and inventory_total when the search counted the whole inventory. The fact sheet is the only evidence for prices, bedroom counts, places, types, amenities, views, completion, furnished, and counts.

An inventory count is supported when it equals inventory_total. A count of the rows on this page is not the inventory when inventory_total is missing. Completion, including off-plan, and furnished may be stated when that returned listing's row says so. A building or project name on the sheet may be stated. A rent may be stated per month, week, or year when it is the same money as rent_aed for rental_period: a yearly rent divided by 12 is the monthly figure, divided by 52 is the weekly figure, and a monthly rent times 12 is the yearly figure. A price, a size, or a place that is not on the sheet is still unsupported.

Flag a claim only when the reply states a price, bedroom count, place, property type, amenity, view, or inventory count that the fact sheet, inventory_total, and the notes do not support. Ignore tone, advice, and wording. A number may be written with commas or rounded in words when it matches a fact. When a note says a filter was dropped, the reply may say so; it may not say that filter still applies.

Copy each unsupported claim as a short phrase from the reply. Leave unsupported_claims empty when every concrete claim is supported.
"""


class ListingJustification(BaseModel):
    """Concrete claims in the reply that the listing facts do not support."""

    unsupported_claims: list[str] = Field(default_factory=list)


_FAILED = ListingJustification(unsupported_claims=["justification check failed"])


def judge_listing_reply(
    *,
    message: str,
    reply: str,
    filters: list[str],
    notes: list[str],
    facts: list[dict],
    inventory_total: int | None = None,
) -> list[str]:
    """Unsupported concrete claims, or a single failure phrase when the check itself fails."""
    _router, answer, _sql = build_chat_models()
    runnable = answer.with_structured_output(
        build_strict_output_schema(ListingJustification),
        method="json_schema",
        include_raw=True,
        **constrained_output_options(),
    )
    payload = {
        "message": message,
        "reply": reply,
        "filters": filters,
        "search_notes": notes,
        "inventory_total": inventory_total,
        "listings": [judge_fields(fact) for fact in facts],
    }
    messages = [
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
    ]
    verdict = invoke_structured_with_fallback(runnable, messages, None, _FAILED)
    if not isinstance(verdict, ListingJustification):
        return list(_FAILED.unsupported_claims)
    return [claim.strip() for claim in verdict.unsupported_claims if claim and claim.strip()]
