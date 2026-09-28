from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_core.runnables import RunnableConfig

from agent.enums.routing import TurnKind
from agent.grounding import GroundingIndex
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute
from agent.schemas.sql import SqlDraft, SqlPage
from agent.sql.cards import ListingLoader
from agent.sql.listing_details import ListingDetailLoader
from agent.sql.transit import NearestStationLoader, RailLineLoader


class AgentModels(Protocol):
    """LLM calls the graph is allowed to make. Tests pass a fake."""

    def route_query(
        self,
        *,
        message: str,
        history: str,
        last_need_db: LastNeedDb | None,
        domain_blurbs: str,
        memory_context: str = "",
        property_types: list[str] | None = None,
        config: RunnableConfig | None = None,
    ) -> QueryRoute: ...

    def route_domain(
        self,
        *,
        message: str,
        turn_kind: TurnKind,
        last_need_db: LastNeedDb | None,
        index_text: str,
        config: RunnableConfig | None = None,
    ) -> DomainRoute: ...

    def answer_direct(
        self,
        *,
        message: str,
        history: str,
        memory_block: str = "",
        config: RunnableConfig | None = None,
    ) -> str: ...

    def answer_unavailable(
        self,
        *,
        message: str,
        history: str,
        config: RunnableConfig | None = None,
    ) -> str: ...

    def draft_sql(
        self,
        *,
        message: str,
        history: str,
        catalog: str,
        allowed_tables: list[str],
        assumptions: dict | None,
        query_frame: dict | None,
        previous_error: str | None,
        listing_ids_only: bool = False,
        resolved_names: list[dict] | None = None,
        config: RunnableConfig | None = None,
    ) -> SqlDraft: ...

    def answer_from_sql(
        self,
        *,
        message: str,
        history: str,
        rows: list[dict],
        columns: list[str],
        row_count: int,
        truncated: bool,
        purpose: str,
        assumptions: dict | None,
        memory_block: str = "",
        listing_ids: list[str] | None = None,
        data_note: str = "",
        search_notes: list[str] | None = None,
        filters: list[str] | None = None,
        coverage: list[dict] | None = None,
        config: RunnableConfig | None = None,
    ) -> str: ...


class SqlRunner(Protocol):
    """Runs one read-only SELECT and returns the page of rows.

    `params` is only passed with SQL written in code. Model-drafted SQL is guarded and has none.
    """

    def __call__(self, sql: str, params: dict | None = None) -> SqlPage: ...


@dataclass
class AgentContext:
    """Run-scoped values. `models` and `grounding` are None in production and fakes in tests."""

    user_id: str
    models: AgentModels | None = None
    sql_runner: SqlRunner | None = None
    listing_loader: ListingLoader | None = None
    listing_detail_loader: ListingDetailLoader | None = None
    nearest_station_loader: NearestStationLoader | None = None
    rail_line_loader: RailLineLoader | None = None
    grounding: GroundingIndex | None = None
