"""Streaming chat. Listing results are ids the frontend can render."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from agent.graphs.chat import stream_turn
from common.identity import Caller
from common.ratelimit.decorators import RATE_LIMITS_ATTRIBUTE
from common.ratelimit.keys import by_caller
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import CHAT_REGISTERED, CHAT_VISITOR, RateLimit
from common.utils.helpers import is_valid_uuid

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, max_length=64)

    @field_validator("message")
    @classmethod
    def message_has_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Message is empty.")
        return text

    @field_validator("thread_id")
    @classmethod
    def thread_id_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text or not (is_valid_uuid(text) or text.isalnum()):
            raise ValueError("Thread id must be letters and numbers.")
        return text


def chat_rule(caller: Caller | None) -> RateLimit:
    if isinstance(caller, Caller) and caller.is_registered:
        return CHAT_REGISTERED
    return CHAT_VISITOR


def enforce_chat_limit(request: Request) -> None:
    limiter.enforce(by_caller(request), chat_rule(getattr(request.state, "caller", None)))


@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    enforce_chat_limit(request)
    caller = request.state.caller
    thread_id = body.thread_id or uuid.uuid4().hex
    graph = getattr(request.app.state, "chat_graph", None)
    models = getattr(request.app.state, "chat_models", None)
    sql_runner = getattr(request.app.state, "sql_runner", None)

    async def events() -> AsyncIterator[str]:
        yield ": ok\n\n"
        try:
            async for event in stream_turn(
                body.message,
                thread_id=thread_id,
                user_id=caller.subject_id,
                models=models,
                sql_runner=sql_runner,
                graph=graph,
            ):
                yield _sse(event)
        except Exception:
            from common.logger import get_logger

            get_logger("chat").exception("chat stream failed")
            yield _sse({"event": "error", "detail": "I couldn't complete that reply."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-ID": thread_id,
        },
    )


def _sse(event: dict) -> str:
    name = str(event.get("event") or "message")
    payload = {key: value for key, value in event.items() if key != "event"}
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


setattr(chat, RATE_LIMITS_ATTRIBUTE, (CHAT_VISITOR, CHAT_REGISTERED))
