from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from agent.schemas.routes import Assumptions, DomainRoute, LastNeedDb, QueryRoute


class ChatState(TypedDict, total=False):
    """Working state for one thread. Catalog YAML is cleared before the checkpoint."""

    messages: Annotated[list, add_messages]
    user_id: str
    query_route: QueryRoute | None
    domain_route: DomainRoute | None
    loaded_domains: list[str]
    catalog_context: str
    last_need_db: LastNeedDb | None
    assumptions: Assumptions | None
    awaiting_sql: bool
    query_frame: dict | None
    goal: dict | None
    memory_context: list
    profile: dict
    ignore_defaults: bool
    memory_block: str
    disclosure: str
    memory_question: str
    applied_defaults: list
    pending_forget: dict | None
    behaviour_events: list
    sql_rows: list
    sql_result: dict | None
    listing_ids: list
    session_profile: dict


class ChatInput(TypedDict, total=False):
    """What a caller sends. Prior fields come from the checkpointer."""

    messages: Annotated[list, add_messages]
    session_profile: dict
