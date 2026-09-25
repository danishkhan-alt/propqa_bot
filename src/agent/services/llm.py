from __future__ import annotations

import json
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from agent.enums.routing import TurnKind
from agent.memory.session.follow_up import FrameClass
from agent.prompts.answer import DIRECT_ANSWER_SYSTEM, UNAVAILABLE_SYSTEM
from agent.prompts.domain_router import DOMAIN_ROUTER_SYSTEM
from agent.prompts.query_router import QUERY_ROUTER_SYSTEM
from agent.prompts.reply import STRUCTURED_REPLY_SYSTEM
from agent.prompts.sql import SQL_ANSWER_SYSTEM, SQL_DRAFT_SYSTEM
from agent.schemas.reply import StructuredReply
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
REPLY_FALLBACK = StructuredReply(
    intro_text="Sorry, I couldn't put that answer together just now. Could you ask me again?"
)


def output_schema(model: type[BaseModel]) -> dict:
    """The JSON schema a structured call is constrained to, with every field required.

    The API allows at most 24 optional and 16 union-typed fields, and each optional field
    makes the grammar slower to compile. Here every field is required, nullable ones as
    unions, so the model always writes each field. Python defaults still apply wherever
    code builds these models. Objects are closed, as OpenAI's strict mode requires.
    """
    schema = model.model_json_schema(mode="serialization")
    defs = schema.get("$defs", {})
    shaped = _inline_annotated_refs({key: value for key, value in schema.items() if key != "$defs"}, defs)
    used = _referenced_defs(shaped, defs)
    if used:
        shaped["$defs"] = {name: _inline_annotated_refs(defs[name], defs) for name in used}
    return _require_every_property(shaped)


def _referenced_defs(node, defs: dict) -> list[str]:
    """Definitions still reached by a $ref, following refs inside definitions too."""
    found: list[str] = []
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, dict):
            ref = current.get("$ref")
            name = ref.removeprefix("#/$defs/") if isinstance(ref, str) else None
            if name in defs and name not in found:
                found.append(name)
                pending.append(_inline_annotated_refs(defs[name], defs))
            pending.extend(current.values())
    return found


def _inline_annotated_refs(node, defs: dict):
    """Strict mode rejects a $ref with sibling keywords, so inline that definition instead.

    The field's description is kept; its default is dropped, since every field is written.
    """
    if isinstance(node, list):
        return [_inline_annotated_refs(item, defs) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and len(node) > 1 and ref.startswith("#/$defs/"):
        target = defs.get(ref.removeprefix("#/$defs/"))
        if isinstance(target, dict):
            siblings = {key: value for key, value in node.items() if key not in ("$ref", "default")}
            return _inline_annotated_refs({**target, **siblings}, defs)
    return {key: _inline_annotated_refs(value, defs) for key, value in node.items()}


def _require_every_property(node):
    if isinstance(node, dict):
        shaped = {key: _require_every_property(value) for key, value in node.items()}
        if isinstance(shaped.get("properties"), dict):
            shaped["required"] = list(shaped["properties"])
            shaped["additionalProperties"] = False
        return shaped
    if isinstance(node, list):
        return [_require_every_property(item) for item in node]
    return node


def invoke_structured(
    runnable, messages: list, config: RunnableConfig | None, fallback
):
    """Call a structured runnable once, retry once, then return the fallback.

    The reply is validated as the fallback's model inside each attempt, so an answer of the
    wrong shape is retried and then replaced, never raised into the graph.
    """
    shape = type(fallback)

    def once(payload: list):
        result = runnable.invoke(payload, config=config)
        if isinstance(result, dict) and "parsed" in result:
            error = result.get("parsing_error")
            if error:
                raise ValueError(str(error))
            result = result.get("parsed")
            if result is None:
                raise ValueError("structured output was empty")
        return result if isinstance(result, shape) else shape.model_validate(result)

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


def _anthropic_chat_models():
    from langchain_anthropic import ChatAnthropic

    from config import ActiveConfig

    api_key = ActiveConfig.ANTHROPIC_API_KEY or None

    def main(effort: str):
        # Thinking tokens come out of max_tokens, so each route gets the full output
        # budget and an explicit effort instead of a small hard cap.
        return ChatAnthropic(
            model=ActiveConfig.AI_MODEL,
            api_key=api_key,
            max_tokens=ActiveConfig.LLM_MAX_OUTPUT_TOKENS,
            thinking={"type": "adaptive"},
            effort=effort,
        )

    router = ChatAnthropic(model=ActiveConfig.ROUTER_MODEL, api_key=api_key, max_tokens=1024)
    return router, main(ActiveConfig.AI_REPLY_EFFORT), main(ActiveConfig.AI_SQL_EFFORT)


def _openai_chat_models():
    from langchain_openai import ChatOpenAI

    from config import ActiveConfig

    api_key = ActiveConfig.OPENAI_API_KEY or None

    def build(model: str, effort: str, max_tokens: int):
        # Reasoning tokens come out of max_tokens, as with Claude's thinking. A model that
        # does not reason (gpt-4.1, gpt-4o) rejects the effort setting, so it gets none.
        reasoning = {"reasoning_effort": effort} if effort and openai_model_reasons(model) else {}
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            stream_usage=True,
            **reasoning,
        )

    # The router reasons as well, so it needs more headroom than a Claude router.
    router = build(ActiveConfig.ROUTER_MODEL, ActiveConfig.ROUTER_EFFORT, 4096)
    answer = build(ActiveConfig.AI_MODEL, ActiveConfig.AI_REPLY_EFFORT, ActiveConfig.LLM_MAX_OUTPUT_TOKENS)
    sql = build(ActiveConfig.AI_MODEL, ActiveConfig.AI_SQL_EFFORT, ActiveConfig.LLM_MAX_OUTPUT_TOKENS)
    return router, answer, sql


def openai_model_reasons(model: str) -> bool:
    """OpenAI's reasoning families: the o-series and gpt-5, except its non-reasoning chat variant."""
    name = model.lower().rsplit("/", 1)[-1]
    if name.startswith("gpt-5"):
        return "-chat" not in name
    return len(name) > 1 and name[0] == "o" and name[1].isdigit()


_PROVIDERS = {"anthropic": _anthropic_chat_models, "openai": _openai_chat_models}


def constrained_output_options() -> dict:
    """Options that make a json_schema call enforce its schema on the active provider.

    Claude's json_schema method always constrains decoding. OpenAI only does when strict
    is set; without it the schema is a hint, and the model can answer in another shape.
    """
    from config import ActiveConfig

    return {"strict": True} if ActiveConfig.LLM_PROVIDER == "openai" else {}


def cached_system(text: str) -> SystemMessage:
    """A system message the provider may reuse across calls that start with it.

    OpenAI caches any repeated prefix of 1024 tokens or more on its own. Claude caches
    only up to a block marked with cache_control, so the marker is added there.
    """
    from config import ActiveConfig

    if ActiveConfig.LLM_PROVIDER == "anthropic":
        return SystemMessage(content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])
    return SystemMessage(content=text)


def build_chat_models():
    """(router, answer, sql) chat models from the provider set by LLM_PROVIDER."""
    from config import ActiveConfig

    provider = ActiveConfig.LLM_PROVIDER
    if provider not in _PROVIDERS:
        raise ValueError(
            f"LLM_PROVIDER={provider!r} is not supported; use one of {sorted(_PROVIDERS)}"
        )
    return _PROVIDERS[provider]()


class RouterModels:
    """Fast model for routing. The main model drafts SQL and writes the answer."""

    def __init__(self) -> None:
        router_llm, answer_llm, sql_llm = build_chat_models()
        constrained = constrained_output_options()
        self._query = router_llm.with_structured_output(
            output_schema(QueryRoute), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "router.query"})
        self._domain = router_llm.with_structured_output(
            output_schema(DomainRoute), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "router.domain"})
        self._answer = answer_llm.with_config({"run_name": "answer.direct"})
        self._sql_answer = answer_llm.with_config({"run_name": "answer.synthesize"})
        # A JSON-schema dict (not the model class) makes the parser yield partial objects
        # while streaming, so intro_text reaches the user as it is written.
        self._reply = answer_llm.with_structured_output(
            StructuredReply.model_json_schema(), method="json_schema"
        ).with_config({"run_name": "answer.structured"})
        self._sql = sql_llm.with_structured_output(
            output_schema(SqlDraft), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "sql.generate"})
        self._frame = router_llm.with_structured_output(
            output_schema(FrameClass), method="json_schema", include_raw=True, **constrained
        ).with_config({"run_name": "memory.frame"})

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
        return invoke_structured(self._query, messages, config, QUERY_FALLBACK)

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
        return invoke_structured(self._domain, messages, config, DOMAIN_FALLBACK)

    def stream_answer_direct(
        self,
        *,
        message: str,
        history: str,
        memory_block: str = "",
        config: RunnableConfig | None = None,
    ):
        yield from _llm_deltas(
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
        config: RunnableConfig | None = None,
    ):
        yield from _llm_deltas(
            self._answer,
            [
                SystemMessage(content=UNAVAILABLE_SYSTEM),
                HumanMessage(
                    content=json.dumps(
                        {"history": history, "message": message}, ensure_ascii=False
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
        config: RunnableConfig | None = None,
    ) -> str:
        return "".join(
            self.stream_answer_unavailable(message=message, history=history, config=config)
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
        return invoke_structured(
            self._sql,
            [
                cached_system(instructions),
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
        listing_ids: list[str] | None = None,
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
            "listing_ids": listing_ids,
            "data_note": data_note,
            "search_notes": search_notes or [],
            "filters": filters or [],
            "coverage": coverage or [],
        }
        yield from _llm_deltas(
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
        listing_ids: list[str] | None = None,
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
                listing_ids=listing_ids,
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
        }
        messages = [
            cached_system(STRUCTURED_REPLY_SYSTEM),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
        ]
        return stream_structured_reply(self._reply, messages, config, on_text)

    def classify_frame(
        self,
        *,
        message: str,
        frame: dict,
        config: RunnableConfig | None = None,
    ) -> str:
        payload = {"message": message, "query_frame": {key: value for key, value in frame.items() if key != "sql"}}
        return invoke_structured(
            self._frame,
            [
                SystemMessage(content=FRAME_CLASS_SYSTEM),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
            ],
            config,
            FRAME_FALLBACK,
        ).kind


def stream_structured_reply(
    runnable,
    messages: list,
    config: RunnableConfig | None,
    on_text: Callable[[str], None] | None,
) -> StructuredReply:
    """Stream intro_text through `on_text`, then validate the whole reply.

    If the stream breaks after text was shown, keep that text rather than replace it.
    If it breaks before, fall back to one non-streaming call with a retry.
    """
    shown = ""
    latest: dict = {}
    try:
        for partial in runnable.stream(messages, config=config):
            if not isinstance(partial, dict):
                continue
            latest = partial
            text = partial.get("intro_text")
            # A partial string only grows. Anything else is a half-parsed escape; wait for more.
            if isinstance(text, str) and len(text) > len(shown) and text.startswith(shown):
                delta, shown = text[len(shown):], text
                if on_text is not None:
                    on_text(delta)
        return StructuredReply.model_validate(latest)
    except Exception as exc:
        logger.warning(
            "answer.structured stream failed",
            extra={"extra_data": {"error": type(exc).__name__, "shown": bool(shown)}},
        )
        if shown.strip():
            return StructuredReply(intro_text=shown)
    reply = invoke_structured(runnable, messages, config, REPLY_FALLBACK)
    if on_text is not None and reply.intro_text:
        on_text(reply.intro_text)
    return reply


def _llm_deltas(runnable, messages: list, config: RunnableConfig | None):
    for chunk in runnable.stream(messages, config=config):
        text = _chunk_text(chunk)
        if text:
            yield text


def _chunk_text(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def _message_text(result) -> str:
    content = result.content
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


_models: RouterModels | None = None


def default_models() -> RouterModels:
    global _models
    if _models is None:
        _models = RouterModels()
    return _models
