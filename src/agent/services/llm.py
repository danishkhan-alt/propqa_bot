from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.enums.routing import TurnKind
from agent.memory.session.follow_up import FrameClass
from agent.prompts.answer import DIRECT_ANSWER_SYSTEM, UNAVAILABLE_SYSTEM
from agent.prompts.domain_router import DOMAIN_ROUTER_SYSTEM
from agent.prompts.query_router import QUERY_ROUTER_SYSTEM
from agent.prompts.sql import SQL_ANSWER_SYSTEM, SQL_DRAFT_SYSTEM
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute
from agent.schemas.sql import SqlDraft
from common.logger import get_logger

logger = get_logger("agent.router")

QUERY_FALLBACK = QueryRoute(
    route="need_db",
    turn_kind="new",
    confidence=0.3,
    rationale="Router output was invalid; defaulting to a database lookup.",
)

DOMAIN_FALLBACK = DomainRoute(
    domain_ids=[],
    join_ids=[],
    confidence=0.3,
    rationale="Domain router output was invalid.",
)

FRAME_CLASS_SYSTEM = """Classify this follow-up against the current query frame. Do not answer the user.

kind is one of:
- refine: same search, with a change to filters, sort, projection, or a row reference
- pivot: same place or property, different subject
- new: unrelated request
"""

FRAME_FALLBACK = FrameClass(kind="new")

SQL_DRAFT_FALLBACK = SqlDraft(sql="", purpose="The draft was empty.")


def invoke_structured(
    runnable, messages: list, config: RunnableConfig | None, fallback
):
    """Call a structured runnable once, retry once, then return the fallback."""

    def once(payload: list):
        result = runnable.invoke(payload, config=config)
        if isinstance(result, dict) and "parsed" in result:
            error = result.get("parsing_error")
            if error:
                raise ValueError(str(error))
            parsed = result.get("parsed")
            if parsed is None:
                raise ValueError("structured output was empty")
            return parsed
        return result

    try:
        return once(messages)
    except Exception as first_error:
        logger.warning(
            "router structured output failed",
            extra={"extra_data": {"error": type(first_error).__name__}},
        )
        retry = [
            *messages,
            HumanMessage(content="Return valid JSON matching the schema. No prose."),
        ]
        try:
            return once(retry)
        except Exception as second_error:
            logger.warning(
                "router structured output retry failed",
                extra={"extra_data": {"error": type(second_error).__name__}},
            )
            return fallback


class AnthropicRouterModels:
    """Fast Claude for routing. The main model drafts SQL and writes the answer."""

    def __init__(self) -> None:
        from langchain_anthropic import ChatAnthropic

        from config import ActiveConfig

        api_key = ActiveConfig.ANTHROPIC_API_KEY or None
        router_llm = ChatAnthropic(
            model=ActiveConfig.ROUTER_MODEL, api_key=api_key, max_tokens=1024
        )
        answer_llm = ChatAnthropic(
            model=ActiveConfig.AI_MODEL,
            api_key=api_key,
            max_tokens=min(ActiveConfig.ANTHROPIC_MAX_OUTPUT_TOKENS, 1024),
        )
        self._query = router_llm.with_structured_output(
            QueryRoute, method="json_schema", include_raw=True
        ).with_config({"run_name": "router.query"})
        self._domain = router_llm.with_structured_output(
            DomainRoute, method="json_schema", include_raw=True
        ).with_config({"run_name": "router.domain"})
        self._answer = answer_llm.with_config({"run_name": "answer.direct"})
        self._sql_answer = answer_llm.with_config({"run_name": "answer.synthesize"})
        sql_llm = ChatAnthropic(
            model=ActiveConfig.AI_MODEL,
            api_key=api_key,
            max_tokens=min(ActiveConfig.ANTHROPIC_MAX_OUTPUT_TOKENS, 2048),
        )
        self._sql = sql_llm.with_structured_output(
            SqlDraft, method="json_schema", include_raw=True
        ).with_config({"run_name": "sql.generate"})
        self._frame = router_llm.with_structured_output(
            FrameClass, method="json_schema", include_raw=True
        ).with_config({"run_name": "memory.frame"})

    def route_query(
        self,
        *,
        message: str,
        history: str,
        last_need_db: LastNeedDb | None,
        domain_blurbs: str,
        memory_context: str = "",
        config: RunnableConfig | None = None,
    ) -> QueryRoute:
        payload = {
            "message": message,
            "history": history,
            "last_need_db": last_need_db.model_dump() if last_need_db else None,
            "domain_blurbs": domain_blurbs,
            "memory_context": memory_context,
        }
        messages = [
            SystemMessage(content=QUERY_ROUTER_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
        parsed = invoke_structured(self._query, messages, config, QUERY_FALLBACK)
        return (
            parsed
            if isinstance(parsed, QueryRoute)
            else QueryRoute.model_validate(parsed)
        )

    def route_domain(
        self,
        *,
        message: str,
        turn_kind: TurnKind,
        last_need_db: LastNeedDb | None,
        index_text: str,
        config: RunnableConfig | None = None,
    ) -> DomainRoute:
        payload = {
            "message": message,
            "turn_kind": turn_kind.value,
            "last_need_db": last_need_db.model_dump() if last_need_db else None,
            "index": index_text,
        }
        messages = [
            SystemMessage(content=DOMAIN_ROUTER_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ]
        parsed = invoke_structured(self._domain, messages, config, DOMAIN_FALLBACK)
        return (
            parsed
            if isinstance(parsed, DomainRoute)
            else DomainRoute.model_validate(parsed)
        )

    def answer_direct(
        self,
        *,
        message: str,
        history: str,
        memory_block: str = "",
        config: RunnableConfig | None = None,
    ) -> str:
        result = self._answer.invoke(
            [
                SystemMessage(content=DIRECT_ANSWER_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"history": history, "message": message, "memory_block": memory_block},
                        ensure_ascii=False,
                    )
                ),
            ],
            config=config,
        )
        return _message_text(result)

    def answer_unavailable(
        self,
        *,
        message: str,
        history: str,
        config: RunnableConfig | None = None,
    ) -> str:
        result = self._answer.invoke(
            [
                SystemMessage(content=UNAVAILABLE_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"history": history, "message": message}, ensure_ascii=False
                    )
                ),
            ],
            config=config,
        )
        return _message_text(result)

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
        config: RunnableConfig | None = None,
    ) -> SqlDraft:
        payload = {
            "message": message,
            "history": history,
            "catalog": catalog,
            "allowed_tables": allowed_tables,
            "assumptions": assumptions,
            "query_frame": query_frame,
            "previous_error": previous_error,
        }
        parsed = invoke_structured(
            self._sql,
            [
                SystemMessage(content=SQL_DRAFT_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config,
            SQL_DRAFT_FALLBACK,
        )
        return parsed if isinstance(parsed, SqlDraft) else SqlDraft.model_validate(parsed)

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
        config: RunnableConfig | None = None,
    ) -> str:
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
        }
        result = self._sql_answer.invoke(
            [
                SystemMessage(content=SQL_ANSWER_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config=config,
        )
        return _message_text(result)

    def classify_frame(
        self,
        *,
        message: str,
        frame: dict,
        config: RunnableConfig | None = None,
    ) -> str:
        payload = {"message": message, "query_frame": {key: value for key, value in frame.items() if key != "sql"}}
        parsed = invoke_structured(
            self._frame,
            [
                SystemMessage(content=FRAME_CLASS_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config,
            FRAME_FALLBACK,
        )
        kind = parsed.kind if isinstance(parsed, FrameClass) else FrameClass.model_validate(parsed).kind
        return kind


def _message_text(result) -> str:
    content = result.content
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


_models: AnthropicRouterModels | None = None


def default_models() -> AnthropicRouterModels:
    global _models
    if _models is None:
        _models = AnthropicRouterModels()
    return _models
