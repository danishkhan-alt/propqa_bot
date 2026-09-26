"""One model call each: retried once, validated, and replaced by a fallback rather than raised."""

from __future__ import annotations

from collections.abc import Callable

import anthropic
import openai
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.schemas.reply import StructuredReply
from agent.services.llm.fallbacks import REPLY_FALLBACK
from common.logger import get_logger

logger = get_logger("agent.router")

_TRANSIENT_CLIENT_STATUS_CODES = frozenset({408, 409, 429})


def invoke_structured_with_fallback(
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
        if is_permanent_api_error(first_error):
            return fallback
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


def is_permanent_api_error(error: Exception) -> bool:
    """A 4xx the provider SDK does not retry (bad request, auth, not found, too long).

    The same request fails the same way again, so a second attempt only adds a round trip.
    408, 409, and 429 are transient, as are 5xx and connection errors.
    """
    if not isinstance(error, (anthropic.APIStatusError, openai.APIStatusError)):
        return False
    return 400 <= error.status_code < 500 and error.status_code not in _TRANSIENT_CLIENT_STATUS_CODES


def stream_structured_reply_with_fallback(
    runnable,
    messages: list,
    config: RunnableConfig | None,
    on_text: Callable[[str], None] | None,
) -> StructuredReply:
    """Stream intro_text through `on_text`, then validate the whole reply.

    If the stream breaks after text was shown, keep that text rather than replace it.
    If it breaks before, fall back to one non-streaming call with a retry, unless the
    provider rejected the request outright, which a second call would repeat.
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
        if is_permanent_api_error(exc):
            reply = REPLY_FALLBACK
        else:
            reply = invoke_structured_with_fallback(runnable, messages, config, REPLY_FALLBACK)
    if on_text is not None and reply.intro_text:
        on_text(reply.intro_text)
    return reply


def stream_text_deltas(runnable, messages: list, config: RunnableConfig | None):
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
