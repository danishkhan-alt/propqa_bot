"""The models the chat graph calls: routing, SQL drafting, and replies."""

from __future__ import annotations

import json
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.enums.routing import TurnKind
from agent.prompts.answer import DIRECT_ANSWER_SYSTEM, UNAVAILABLE_ANSWER_SYSTEM
from agent.prompts.domain_router import DOMAIN_ROUTER_SYSTEM
from agent.prompts.follow_up import FOLLOW_UP_KIND_SYSTEM
from agent.prompts.query_router import QUERY_ROUTER_SYSTEM
from agent.prompts.reply import FOCUSED_LISTINGS_REPLY_SYSTEM, STRUCTURED_REPLY_SYSTEM
from agent.prompts.sql import SQL_ANSWER_SYSTEM, SQL_DRAFT_SYSTEM
from agent.schemas.follow_up import FollowUpClassification
from agent.schemas.reply import StructuredReply
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute
from agent.schemas.sql import SqlDraft
from agent.services import jev_domain_router
from agent.services.jev_domain_router import build_jev_client
from agent.services.llm.calls import (
    invoke_structured_with_fallback,
    stream_structured_reply_with_fallback,
    stream_text_deltas,
)
from agent.services.llm.fallbacks import (
    DOMAIN_ROUTE_FALLBACK,
    FOLLOW_UP_KIND_FALLBACK,
    QUERY_ROUTE_FALLBACK,
    SQL_DRAFT_FALLBACK,
)
from agent.services.llm.output_schema import build_strict_output_schema
from agent.services.llm.providers import build_cached_system_message, build_chat_models, constrained_output_options
from agent.services.typesafe import TypeSafeError
from agent.sql.recipes import load_recipes_by_id
from catalog import list_domains
from common.logger import get_logger

logger = get_logger("agent.router")


class LangChainAgentModels:
    """Fast model for routing. The main model drafts SQL and writes the answer."""

    def __init__(self, domain_router: str | None = None) -> None:
        router_llm, answer_llm, sql_llm = build_chat_models()
        constrained = constrained_output_options()
        self._query = router_llm.with_structured_output(
            build_strict_output_schema(QueryRoute), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "router.query"})
        self._domain = router_llm.with_structured_output(
            build_strict_output_schema(DomainRoute), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "router.domain"})
        self._answer = answer_llm.with_config({"run_name": "answer.direct"})
        self._sql_answer = answer_llm.with_config({"run_name": "answer.synthesize"})
        # A JSON-schema dict (not the model class) makes the parser yield partial objects
        # while streaming, so intro_text reaches the user as it is written.
        self._reply = answer_llm.with_structured_output(
            StructuredReply.model_json_schema(), method="json_schema"
        ).with_config({"run_name": "answer.structured"})
        self._sql = sql_llm.with_structured_output(
            build_strict_output_schema(SqlDraft), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "sql.generate"})
        self._frame = router_llm.with_structured_output(
            build_strict_output_schema(FollowUpClassification), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "memory.frame"})
        self._jev = build_jev_client(domain_router)

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
    ) -> QueryRoute:
        payload = {
            "message": message,
            "history": history,
            "last_need_db": last_need_db.model_dump() if last_need_db else None,
            "domain_blurbs": domain_blurbs,
            "memory_context": memory_context,
            "property_types": property_types or [],
        }
        messages = [
            SystemMessage(content=QUERY_ROUTER_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
        return invoke_structured_with_fallback(self._query, messages, config, QUERY_ROUTE_FALLBACK)

    def route_domain(
        self,
        *,
        message: str,
        turn_kind: TurnKind,
        last_need_db: LastNeedDb | None,
        index_text: str,
        recipes_text: str = "",
        config: RunnableConfig | None = None,
    ) -> DomainRoute:
        if self._jev is not None:
            try:
                return jev_domain_router.route_domain(
                    self._jev,
                    message=message,
                    turn_kind=turn_kind,
                    last_need_db=last_need_db,
                    domains=list_domains(),
                    recipes={item.id: item.when for item in load_recipes_by_id().values()},
                )
            except TypeSafeError as exc:
                logger.warning(
                    "router.domain.jev failed; using the router model",
                    extra={"extra_data": {"error": str(exc)[:300]}},
                )
        payload = {
            "message": message,
            "turn_kind": turn_kind.value,
            "last_need_db": last_need_db.model_dump() if last_need_db else None,
            "index": index_text,
            "recipes": recipes_text,
        }
        messages = [
            SystemMessage(content=DOMAIN_ROUTER_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
        return invoke_structured_with_fallback(self._domain, messages, config, DOMAIN_ROUTE_FALLBACK)

    def stream_answer_direct(
        self,
        *,
        message: str,
        history: str,
        memory_block: str = "",
        config: RunnableConfig | None = None,
    ):
        yield from stream_text_deltas(
            self._answer,
            [
                SystemMessage(content=DIRECT_ANSWER_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"history": history, "message": message, "memory_block": memory_block},
                        ensure_ascii=False,
                    )
                ),
            ],
            config,
        )

    def answer_direct(
        self,
        *,
        message: str,
        history: str,
        memory_block: str = "",
        config: RunnableConfig | None = None,
    ) -> str:
        return "".join(
            self.stream_answer_direct(
                message=message,
                history=history,
                memory_block=memory_block,
                config=config,
            )
        ).strip()

    def stream_answer_unavailable(
        self,
        *,
        message: str,
        history: str,
        missing: str = "",
        config: RunnableConfig | None = None,
    ):
        yield from stream_text_deltas(
            self._answer,
            [
                SystemMessage(content=UNAVAILABLE_ANSWER_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"history": history, "message": message, "missing": missing}, ensure_ascii=False
                    )
                ),
            ],
            config,
        )

    def answer_unavailable(
        self,
        *,
        message: str,
        history: str,
        missing: str = "",
        config: RunnableConfig | None = None,
    ) -> str:
        return "".join(
            self.stream_answer_unavailable(message=message, history=history, missing=missing, config=config)
        ).strip()

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
    ) -> SqlDraft:
        # The catalog and table list depend only on the loaded packs, so they sit in the
        # system prefix, where the provider caches them across turns. Per-turn facts follow.
        instructions = (
            f"{SQL_DRAFT_SYSTEM}\nallowed_tables: {json.dumps(allowed_tables)}\n\ncatalog:\n{catalog}"
        )
        payload = {
            "message": message,
            "history": history,
            "resolved_names": resolved_names or [],
            "assumptions": assumptions,
            "query_frame": query_frame,
            "previous_error": previous_error,
            "listing_ids_only": listing_ids_only,
        }
        return invoke_structured_with_fallback(
            self._sql,
            [
                build_cached_system_message(instructions),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config,
            SQL_DRAFT_FALLBACK,
        )

    def stream_answer_from_sql(
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
        listing_count: int = 0,
        data_note: str = "",
        search_notes: list[str] | None = None,
        filters: list[str] | None = None,
        coverage: list[dict] | None = None,
        config: RunnableConfig | None = None,
    ):
        payload = {
            "message": message,
            "history": history,
            "purpose": purpose,
            "assumptions": assumptions,
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "truncated": truncated,
            "memory_block": memory_block,
            "listing_count": listing_count,
            "data_note": data_note,
            "search_notes": search_notes or [],
            "filters": filters or [],
            "coverage": coverage or [],
        }
        yield from stream_text_deltas(
            self._sql_answer,
            [
                SystemMessage(content=SQL_ANSWER_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config,
        )

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
        listing_count: int = 0,
        data_note: str = "",
        search_notes: list[str] | None = None,
        filters: list[str] | None = None,
        coverage: list[dict] | None = None,
        config: RunnableConfig | None = None,
    ) -> str:
        return "".join(
            self.stream_answer_from_sql(
                message=message,
                history=history,
                rows=rows,
                columns=columns,
                row_count=row_count,
                truncated=truncated,
                purpose=purpose,
                assumptions=assumptions,
                memory_block=memory_block,
                listing_count=listing_count,
                data_note=data_note,
                search_notes=search_notes,
                filters=filters,
                coverage=coverage,
                config=config,
            )
        ).strip()

    def draft_reply(
        self,
        *,
        message: str,
        history: str,
        rows: list[dict] | None = None,
        columns: list[str] | None = None,
        row_count: int = 0,
        truncated: bool = False,
        purpose: str = "",
        assumptions: dict | None = None,
        memory_block: str = "",
        listings: list[dict] | None = None,
        listing_count: int = 0,
        lookup_status: str | None = None,
        data_note: str = "",
        search_notes: list[str] | None = None,
        filters: list[str] | None = None,
        coverage: list[dict] | None = None,
        session_profile: dict | None = None,
        follow_up_question: str | None = None,
        map_available: bool = False,
        on_text: Callable[[str], None] | None = None,
        config: RunnableConfig | None = None,
    ) -> StructuredReply:
        payload = {
            "message": message,
            "history": history,
            "session_profile": session_profile or {},
            "memory_block": memory_block,
            "lookup_status": lookup_status,
            "purpose": purpose,
            "assumptions": assumptions,
            "listing_count": listing_count,
            "listings": listings or [],
            "columns": columns or [],
            "rows": rows or [],
            "row_count": row_count,
            "truncated": truncated,
            "data_note": data_note,
            "search_notes": search_notes or [],
            "filters": filters or [],
            "coverage": coverage or [],
            "follow_up_question": follow_up_question,
            "map_available": map_available,
        }
        messages = [
            build_cached_system_message(STRUCTURED_REPLY_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
        ]
        return stream_structured_reply_with_fallback(self._reply, messages, config, on_text)

    def draft_listing_reply(
        self,
        *,
        message: str,
        history: str,
        listings: list[dict],
        memory_block: str = "",
        data_note: str = "",
        session_profile: dict | None = None,
        map_available: bool = False,
        on_text: Callable[[str], None] | None = None,
        config: RunnableConfig | None = None,
    ) -> StructuredReply:
        """Answer about listings the user picked on screen, from their full advert details."""
        payload = {
            "message": message,
            "history": history,
            "session_profile": session_profile or {},
            "memory_block": memory_block,
            "listings": listings,
            "data_note": data_note,
            "map_available": map_available,
        }
        messages = [
            build_cached_system_message(FOCUSED_LISTINGS_REPLY_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
        ]
        return stream_structured_reply_with_fallback(self._reply, messages, config, on_text)

    def classify_follow_up_kind(
        self,
        *,
        message: str,
        frame: dict,
        config: RunnableConfig | None = None,
    ) -> str:
        payload = {"message": message, "query_frame": {key: value for key, value in frame.items() if key != "sql"}}
        return invoke_structured_with_fallback(
            self._frame,
            [
                SystemMessage(content=FOLLOW_UP_KIND_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config,
            FOLLOW_UP_KIND_FALLBACK,
        ).kind


_models: LangChainAgentModels | None = None


def get_default_models() -> LangChainAgentModels:
    global _models
    if _models is None:
        _models = LangChainAgentModels()
    return _models
