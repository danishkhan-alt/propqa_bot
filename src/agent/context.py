from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from langchain_core.runnables import RunnableConfig

from agent.enums.routing import TurnKind
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute


class RouterModels(Protocol):
    """LLM calls the graph is allowed to make. Tests pass a fake."""

    def route_query(
        self,
        *,
        message: str,
        history: str,
        last_need_db: LastNeedDb | None,
        domain_blurbs: str,
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
        config: RunnableConfig | None = None,
    ) -> str: ...


@dataclass
class AgentContext:
    """Run-scoped values. `models` is None in production and a fake in tests."""

    user_id: str
    models: RouterModels | None = None
