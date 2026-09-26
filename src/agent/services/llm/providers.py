"""Chat models and request options for the provider set by LLM_PROVIDER."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from config import ActiveConfig


def _anthropic_chat_models():
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
    api_key = ActiveConfig.OPENAI_API_KEY or None

    def build(model: str, effort: str, max_tokens: int):
        # Reasoning tokens come out of max_tokens, as with Claude's thinking. A model that
        # does not reason (gpt-4.1, gpt-4o) rejects the effort setting, so it gets none.
        reasoning = {"reasoning_effort": effort} if effort and is_openai_reasoning_model(model) else {}
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


def is_openai_reasoning_model(model: str) -> bool:
    """OpenAI's reasoning families: the o-series and gpt-5, except its non-reasoning chat variant."""
    name = model.lower().rsplit("/", 1)[-1]
    if name.startswith("gpt-5"):
        return "-chat" not in name
    return len(name) > 1 and name[0] == "o" and name[1].isdigit()


_CHAT_MODEL_BUILDERS_BY_PROVIDER = {"anthropic": _anthropic_chat_models, "openai": _openai_chat_models}


def constrained_output_options() -> dict:
    """Options that make a json_schema call enforce its schema on the active provider.

    Claude's json_schema method always constrains decoding. OpenAI only does when strict
    is set; without it the schema is a hint, and the model can answer in another shape.
    """

    return {"strict": True} if ActiveConfig.LLM_PROVIDER == "openai" else {}


def build_cached_system_message(text: str) -> SystemMessage:
    """A system message the provider may reuse across calls that start with it.

    OpenAI caches any repeated prefix of 1024 tokens or more on its own. Claude caches
    only up to a block marked with cache_control, so the marker is added there.
    """

    if ActiveConfig.LLM_PROVIDER == "anthropic":
        return SystemMessage(content=[{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}])
    return SystemMessage(content=text)


def build_chat_models():
    """(router, answer, sql) chat models from the provider set by LLM_PROVIDER."""

    provider = ActiveConfig.LLM_PROVIDER
    if provider not in _CHAT_MODEL_BUILDERS_BY_PROVIDER:
        raise ValueError(
            f"LLM_PROVIDER={provider!r} is not supported; use one of {sorted(_CHAT_MODEL_BUILDERS_BY_PROVIDER)}"
        )
    return _CHAT_MODEL_BUILDERS_BY_PROVIDER[provider]()
