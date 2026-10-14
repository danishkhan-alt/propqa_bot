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

You are given the user's words, the filters the search applied, notes about any filter that was dropped, and a fact sheet of the returned listings. The fact sheet is the only evidence for prices, bedroom counts, places, types, amenities, views, and counts.

Flag a claim only when the reply states a price, bedroom count, place, property type, amenity, view, or inventory count that the fact sheet and the notes do not support. Ignore tone, advice, and wording. A number may be written with commas or rounded in words when it matches a fact. When a note says a filter was dropped, the reply may say so; it may not say that filter still applies.

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
