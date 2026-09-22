from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.enums.routing import TurnKind
from agent.prompts.answer import DIRECT_ANSWER_SYSTEM, UNAVAILABLE_SYSTEM
from agent.prompts.domain_router import DOMAIN_ROUTER_SYSTEM
from agent.prompts.query_router import QUERY_ROUTER_SYSTEM
from agent.schemas.routes import DomainRoute, LastNeedDb, QueryRoute
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
    """Fast Claude for routing, main model for direct answers. No tools."""

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

    def route_query(
        self,
        *,
        message: str,
        history: str,
        last_need_db: LastNeedDb | None,
        domain_blurbs: str,
        config: RunnableConfig | None = None,
    ) -> QueryRoute:
        payload = {
            "message": message,
            "history": history,
            "last_need_db": last_need_db.model_dump() if last_need_db else None,
            "domain_blurbs": domain_blurbs,
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
        config: RunnableConfig | None = None,
    ) -> str:
        result = self._answer.invoke(
            [
                SystemMessage(content=DIRECT_ANSWER_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"history": history, "message": message}, ensure_ascii=False
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
