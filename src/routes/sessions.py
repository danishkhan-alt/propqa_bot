"""Session and preference routes the chat UI calls."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from agent.checkpointer import delete_thread
from agent.graph.workflow import get_chat_graph
from agent.memory.maintenance.privacy import delete_user_memory
from agent.memory.models.records import ALL_CLUSTERS
from agent.memory.session.backends import get_repository
from auth.middleware import require_user_id
from common.logger import get_logger
from common.session import (
    GUEST_USER_ID_PREFIX,
    list_user_sessions,
    preferences,
    remove_sidebar_session,
    restore_turns_from_checkpoint,
    safe_thread_id,
    safe_user_id,
    transfer_sidebar_session,
)
from routes.schemas.sessions import ForgetSessionsRequest, NewSessionRequest, SavePreferencesRequest

logger = get_logger("sessions")
router = APIRouter()


@router.post("/sessions/new")
def new_session(body: NewSessionRequest | None = None) -> dict:
    del body
    return {"session_id": str(uuid.uuid4()), "carried_over": []}


@router.get("/sessions")
def list_sessions(user_id: str | None = None, limit: int = 30) -> dict:
    return {"sessions": [row.to_row() for row in list_user_sessions(user_id, limit)]}


@router.get("/sessions/{session_id}/turns")
async def session_turns(request: Request, session_id: str, limit: int = 30) -> dict:
    thread_id = _require_thread(session_id)
    try:
        snapshot = await _get_chat_graph(request).aget_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        logger.exception("could not read session %s", thread_id)
        raise HTTPException(status_code=503, detail="Could not load this session.") from None
    values = getattr(snapshot, "values", None) or {}
    turns, messages = restore_turns_from_checkpoint(values, limit=limit)
    return {
        "session_id": thread_id,
        "turns": turns,
        "messages": messages,
        "knowledge": {},
        "summary": "",
    }


@router.post("/sessions/forget_many")
def forget_many(request: Request, body: ForgetSessionsRequest) -> dict:
    forgotten = [item for item in body.session_ids if _forget_session(item, request)]
    return {"forgotten": forgotten}


@router.post("/sessions/{session_id}/forget")
def forget_session(request: Request, session_id: str, body: ForgetSessionsRequest | None = None) -> dict:
    del body
    if not _forget_session(session_id, request):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "forgotten"}


@router.post("/sessions/{session_id}/forget_all")
def forget_session_and_user_memory(request: Request, session_id: str, body: ForgetSessionsRequest | None = None) -> dict:
    user_id = safe_user_id(body.user_id) if body is not None else None
    _forget_session(session_id, request)
    if user_id:
        _delete_all_user_memory(user_id)
    return {"status": "forgotten"}


@router.post("/sessions/{session_id}/claim")
def claim_session(request: Request, session_id: str, body: ForgetSessionsRequest | None = None) -> dict:
    """Move a chat started as a guest into the signed-in account's sidebar."""
    user_id = require_user_id(request)
    guest_user_id = (body.guest_user_id if body is not None else None) or ""
    claimed = guest_user_id.startswith(GUEST_USER_ID_PREFIX) and transfer_sidebar_session(
        session_id, guest_user_id, user_id
    )
    return {"status": "ok", "claimed": claimed}


@router.get("/sessions/{session_id}/quota")
def session_quota(session_id: str) -> dict:
    _require_thread(session_id)
    return {"used": 0, "limit": 100, "remaining": 100, "exhausted": False}


@router.get("/sessions/{session_id}/context")
def session_context(session_id: str) -> dict:
    _require_thread(session_id)
    return {"prompt_tokens": 0, "budget": 0, "fraction": 0, "compacted_turns": 0}


@router.post("/sessions/{session_id}/context/compact")
def compact_session(session_id: str) -> dict:
    return session_context(session_id)


@router.get("/preferences")
def get_preferences(user_id: str) -> dict:
    return {"preferences": preferences.load(_require_user(user_id))}


@router.post("/preferences")
def save_preferences(body: SavePreferencesRequest) -> dict:
    merged = preferences.merge(_require_user(body.user_id), body.preferences)
    return {"preferences": merged}


@router.delete("/preferences")
def delete_preferences(user_id: str, session_id: str | None = None) -> dict:
    del session_id
    preferences.clear(_require_user(user_id))
    return {"status": "deleted"}


def _get_chat_graph(request: Request):
    compiled = getattr(request.app.state, "chat_graph", None)
    if compiled is not None:
        return compiled

    return get_chat_graph()


def _require_thread(session_id: str) -> str:
    thread_id = safe_thread_id(session_id)
    if thread_id is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return thread_id


def _require_user(user_id: str) -> str:
    owner = safe_user_id(user_id)
    if owner is None:
        raise HTTPException(status_code=400, detail="user_id is invalid.")
    return owner


def _forget_session(session_id: str, request: Request | None = None) -> bool:
    thread_id = remove_sidebar_session(session_id)
    if thread_id is None:
        return False
    _delete_thread(thread_id, request)
    return True


def _delete_thread(thread_id: str, request: Request | None) -> None:
    graph = getattr(request.app.state, "chat_graph", None) if request is not None else None
    saver = getattr(graph, "checkpointer", None)
    if saver is not None and hasattr(saver, "delete_thread"):
        try:
            saver.delete_thread(thread_id)
        except Exception:
            logger.exception("could not delete session %s", thread_id)
        return
    try:
        delete_thread(thread_id)
    except Exception:
        logger.exception("could not delete session %s", thread_id)


def _delete_all_user_memory(user_id: str) -> None:
    try:
        repository = get_repository()
        if repository is None:
            return
        for cluster in ALL_CLUSTERS:
            delete_user_memory(repository, user_id, cluster=cluster)
    except Exception:
        logger.exception("could not clear memory for %s", user_id)
