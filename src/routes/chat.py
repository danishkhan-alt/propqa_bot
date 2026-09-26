"""Streaming chat. Listing results arrive as cards the frontend can render."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from agent.graph.runner import stream_turn
from common.identity import Caller
from common.logger import get_logger
from common.ratelimit.decorators import RATE_LIMITS_ATTRIBUTE
from common.ratelimit.keys import caller_rate_limit_key
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import CHAT_REGISTERED, CHAT_VISITOR
from common.schemas.rate_limit import RateLimit
from common.session import record_session_activity
from routes.schemas.chat import ChatRequest

router = APIRouter()


def chat_rate_limit_for(caller: Caller | None) -> RateLimit:
    if isinstance(caller, Caller) and caller.is_registered:
        return CHAT_REGISTERED
    return CHAT_VISITOR


def enforce_chat_limit(request: Request) -> None:
    limiter.enforce(caller_rate_limit_key(request), chat_rate_limit_for(getattr(request.state, "caller", None)))


@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    enforce_chat_limit(request)
    caller = request.state.caller
    thread_id = body.thread_id or body.session_id or uuid.uuid4().hex
    user_id = body.user_id or caller.subject_id
    record_session_activity(user_id, thread_id, body.message)
    graph = getattr(request.app.state, "chat_graph", None)
    models = getattr(request.app.state, "chat_models", None)
    sql_runner = getattr(request.app.state, "sql_runner", None)
    listing_loader = getattr(request.app.state, "listing_loader", None)
    listing_detail_loader = getattr(request.app.state, "listing_detail_loader", None)

    async def events() -> AsyncIterator[str]:
        yield ": ok\n\n"
        try:
            async for event in stream_turn(
                body.message,
                thread_id=thread_id,
                user_id=user_id,
                models=models,
                sql_runner=sql_runner,
                listing_loader=listing_loader,
                listing_detail_loader=listing_detail_loader,
                graph=graph,
                session_profile=body.session_profile,
                focused_property_ids=body.focused_property_ids,
            ):
                yield _format_sse_event(event)
        except Exception:
            get_logger("chat").exception("chat stream failed")
            yield _format_sse_event({"event": "error", "detail": "I couldn't complete that reply."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-ID": thread_id,
        },
    )


def _format_sse_event(event: dict) -> str:
    name, payload = _client_payload(event)
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _client_payload(event: dict) -> tuple[str, dict]:
    """Shape each event so the UI frame parser can read the ``data`` line alone."""
    name = str(event.get("event") or "message")
    payload = {key: value for key, value in event.items() if key != "event"}
    if name == "text" and "delta" in payload and "token" not in payload:
        payload["token"] = payload["delta"]
    elif name == "done":
        payload["done"] = True
    elif name == "error" and "error" not in payload:
        payload["error"] = str(payload.get("detail") or "I couldn't complete that reply.")
    return name, payload


setattr(chat, RATE_LIMITS_ATTRIBUTE, (CHAT_VISITOR, CHAT_REGISTERED))
