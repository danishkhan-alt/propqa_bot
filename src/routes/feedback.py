"""Thumbs on an assistant reply. The vote lives in the chatbot database, not the checkpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from agent.graph.workflow import get_chat_graph
from agent.services.tracing import record_user_feedback
from common.errors import InvalidRequestBody
from common.feedback import feedback_store_for
from common.identity import Caller
from common.logger import get_logger
from common.ratelimit.declared import declare_rate_limits
from common.ratelimit.keys import caller_rate_limit_key
from common.ratelimit.limiter import limiter
from common.ratelimit.rules import API_REGISTERED, API_VISITOR
from common.schemas.rate_limit import RateLimit
from common.session.transcript import resolve_feedback_turn
from routes.schemas.feedback import ThumbsRequest

logger = get_logger("feedback")
router = APIRouter()


def feedback_rate_limit_for(caller: Caller | None) -> RateLimit:
    if isinstance(caller, Caller) and caller.is_registered:
        return API_REGISTERED
    return API_VISITOR


@router.post("/feedback/thumbs")
async def thumbs(request: Request, body: ThumbsRequest) -> dict:
    limiter.enforce(
        caller_rate_limit_key(request),
        feedback_rate_limit_for(getattr(request.state, "caller", None)),
    )
    store = feedback_store_for(request)
    if store is None:
        raise HTTPException(status_code=503, detail="Feedback is unavailable right now.")

    values = await _checkpoint_values(request, body.session_id)
    turn_id, trace_id = resolve_feedback_turn(
        values,
        turn_id=body.turn_id,
        user_message=body.user_message,
        assistant_message=body.assistant_message,
    )
    if not turn_id:
        raise InvalidRequestBody("A turn id or the user and assistant text is required.")
    if trace_id is None:
        try:
            trace_id = store.trace_for(body.session_id, turn_id)
        except Exception:
            logger.warning("could not read the stored trace id", exc_info=True)
            trace_id = None
    try:
        store.save(
            session_id=body.session_id,
            turn_id=turn_id,
            thumbs=body.thumbs,
            comment=body.comment,
            trace_id=trace_id,
        )
    except Exception:
        logger.exception("could not store thumbs for %s", body.session_id)
        raise HTTPException(status_code=503, detail="Feedback is unavailable right now.") from None

    record_user_feedback(trace_id, body.thumbs, body.comment)
    return {"ok": True, "turn_id": turn_id, "thumbs": body.thumbs}


async def _checkpoint_values(request: Request, session_id: str) -> dict:
    graph = getattr(request.app.state, "chat_graph", None)
    if graph is None:
        try:
            graph = get_chat_graph()
        except Exception:
            logger.warning("feedback checkpoint unavailable", exc_info=True)
            return {}
    try:
        snapshot = await graph.aget_state({"configurable": {"thread_id": session_id}})
    except Exception:
        logger.warning("feedback checkpoint read failed", exc_info=True)
        return {}
    values = getattr(snapshot, "values", None) or {}
    return values if isinstance(values, dict) else {}


declare_rate_limits(thumbs, API_VISITOR, API_REGISTERED)
