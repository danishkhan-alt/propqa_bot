"""What each structured call returns when the model's answer cannot be used."""

from __future__ import annotations

from agent.schemas.follow_up import FollowUpClassification
from agent.schemas.reply import StructuredReply
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlDraft

QUERY_ROUTE_FALLBACK = QueryRoute(
    route="need_db",
    turn_kind="new",
    confidence=0.3,
    rationale="Router output was invalid; defaulting to a database lookup.",
)

DOMAIN_ROUTE_FALLBACK = DomainRoute(
    domain_ids=[],
    join_ids=[],
    confidence=0.3,
    rationale="Domain router output was invalid.",
)

FOLLOW_UP_KIND_FALLBACK = FollowUpClassification(kind="new")

SQL_DRAFT_FALLBACK = SqlDraft(sql="", purpose="The draft was empty.")
REPLY_FALLBACK = StructuredReply(
    intro_text="Sorry, I couldn't put that answer together just now. Could you ask me again?"
)
