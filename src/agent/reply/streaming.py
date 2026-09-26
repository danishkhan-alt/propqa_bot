"""Stream a reply to the UI as it is written: prose, a structured reply, or memory notes.

Every piece of text goes out through `publish_stream_event` as soon as it exists, and the function
returns the full text so the caller can store it in the chat history.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from agent.context import AgentModels
from agent.memory.read.prompt_text import append_memory_notes
from agent.reply.figures import build_reply_blocks
from agent.schemas.profile import ProfileQuestion
from agent.schemas.reply import StructuredReply
from agent.services.stream_events import publish_stream_event
from agent.services.transcript import (
    ANSWER_HISTORY_MESSAGE_LIMIT,
    format_recent_history,
)
from common.logger import get_logger

logger = get_logger("agent.reply")


def stream_prose_reply(models: AgentModels, method_name: str, **kwargs) -> str:
    """Stream each text piece as the model produces it, and return the reply."""
    stream = getattr(models, f"stream_{method_name}", None)
    if callable(stream):
        parts: list[str] = []
        for delta in stream(**kwargs):
            piece = delta if isinstance(delta, str) else str(delta or "")
            if not piece:
                continue
            parts.append(piece)
            publish_stream_event("text", delta=piece)
        return "".join(parts).strip()
    text = str(getattr(models, method_name)(**kwargs) or "").strip()
    if text:
        publish_stream_event("text", delta=text)
    return text


def stream_memory_notes(text: str, disclosure: str, memory_question: str) -> str:
    """Append the saved-preference disclosure and memory question, streaming only what was added."""
    noted = append_memory_notes(text, disclosure, memory_question)
    added = noted[len(text) :] if noted.startswith(text) else ""
    if added.strip():
        publish_stream_event("text", delta=added)
    return noted


def publish_structured_reply(
    models: AgentModels,
    *,
    method_name: str = "draft_reply",
    message: str,
    messages: list,
    session_profile: dict,
    question: ProfileQuestion | None,
    config: RunnableConfig,
    **fields,
) -> str | None:
    """Stream a structured reply when the model supports it. Otherwise the caller streams prose."""
    draft = getattr(models, method_name, None)
    if not callable(draft):
        return None
    if question is not None:
        fields["follow_up_question"] = question.prompt
    try:
        parsed = draft(
            message=message,
            history=format_recent_history(messages, limit=ANSWER_HISTORY_MESSAGE_LIMIT),
            session_profile=session_profile,
            on_text=lambda delta: publish_stream_event("text", delta=delta),
            config=config,
            **fields,
        )
    except Exception:
        logger.warning("answer.structured failed", exc_info=True)
        return None
    reply = (
        parsed
        if isinstance(parsed, StructuredReply)
        else StructuredReply.model_validate(parsed)
    )
    payload = reply.model_dump()
    # Listings have their own photo cards, so their rows are never laid out as figures.
    figure_rows = [] if fields.get("listings") else list(fields.get("rows") or [])
    payload.update(
        build_reply_blocks(reply, figure_rows, list(fields.get("columns") or []))
    )
    payload["question"] = question.to_ui_payload() if question is not None else None
    if question is not None:
        # The question already has its own tap options; a chip repeating it is noise.
        asked = question.prompt.casefold()
        payload["suggested_followups"] = [
            item for item in reply.suggested_followups if item.casefold() not in asked
        ]
    note = fields.get("data_note") or ""
    if note and not payload.get("data_source_note"):
        payload["data_source_note"] = note
    payload["session_profile"] = session_profile
    publish_stream_event("reply", type="reply", reply=payload)
    return reply.intro_text.strip()
