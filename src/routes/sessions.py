"""Session and preference routes the chat UI calls."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from common.logger import get_logger
from common.session import (
    detach_session,
    preferences,
    safe_thread_id,
    safe_user_id,
    sessions_for,
    turns_from,
)

logger = get_logger("sessions")
router = APIRouter()


class NewSession(BaseModel):
    model_config = ConfigDict(extra="ignore")

    previous_session_id: str | None = None
    user_id: str | None = None
    carry_over_long_term: bool = True


class ForgetBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    session_ids: list[str] = Field(default_factory=list)
    guest_user_id: str | None = None
    merge_ltm: bool = True


class PreferencesBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    preferences: dict = Field(default_factory=dict)


@router.post("/sessions/new")
def new_session(body: NewSession | None = None) -> dict:
    del body
    return {"session_id": str(uuid.uuid4()), "carried_over": []}


@router.get("/sessions")
def list_sessions(user_id: str | None = None, limit: int = 30) -> dict:
    return {"sessions": [row.to_row() for row in sessions_for(user_id, limit)]}


@router.get("/sessions/{session_id}/turns")
async def session_turns(request: Request, session_id: str, limit: int = 30) -> dict:
    thread_id = _require_thread(session_id)
    try:
        snapshot = await _graph(request).aget_state({"configurable": {"thread_id": thread_id}})
    except Exception:
        logger.exception("could not read session %s", thread_id)
        raise HTTPException(status_code=503, detail="Could not load this session.") from None
    values = getattr(snapshot, "values", None) or {}
    turns, messages = turns_from(values, limit=limit)
    return {
        "session_id": thread_id,
        "turns": turns,
        "messages": messages,
        "knowledge": {},
        "summary": "",
    }


@router.post("/sessions/forget_many")
def forget_many(request: Request, body: ForgetBody) -> dict:
    forgotten = [item for item in body.session_ids if _drop(item, request)]
    return {"forgotten": forgotten}


@router.post("/sessions/{session_id}/forget")
def forget_session(request: Request, session_id: str, body: ForgetBody | None = None) -> dict:
    del body
    if not _drop(session_id, request):
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "forgotten"}


@router.post("/sessions/{session_id}/forget_all")
def forget_all(request: Request, session_id: str, body: ForgetBody | None = None) -> dict:
    user_id = safe_user_id(body.user_id) if body is not None else None
    _drop(session_id, request)
    if user_id:
        _wipe_memory(user_id)
    return {"status": "forgotten"}


@router.post("/sessions/{session_id}/claim")
def claim_session(session_id: str, body: ForgetBody | None = None) -> dict:
    del session_id, body
    return {"status": "ok"}


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
def save_preferences(body: PreferencesBody) -> dict:
    merged = preferences.merge(_require_user(body.user_id), body.preferences)
    return {"preferences": merged}


@router.delete("/preferences")
def delete_preferences(user_id: str, session_id: str | None = None) -> dict:
    del session_id
    preferences.clear(_require_user(user_id))
    return {"status": "deleted"}


def _graph(request: Request):
    compiled = getattr(request.app.state, "chat_graph", None)
    if compiled is not None:
        return compiled
    from agent.graphs.workflow import get_chat_graph

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


def _drop(session_id: str, request: Request | None = None) -> bool:
    thread_id = detach_session(session_id)
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
        from agent.checkpointer import delete_thread

        delete_thread(thread_id)
    except Exception:
        logger.exception("could not delete session %s", thread_id)


def _wipe_memory(user_id: str) -> None:
    try:
        from agent.memory.maintenance.privacy import delete_user_memory
        from agent.memory.models.types import ALL_CLUSTERS
        from agent.memory.session.bootstrap import get_repository

        repository = get_repository()
        if repository is None:
            return
        for cluster in ALL_CLUSTERS:
            delete_user_memory(repository, user_id, cluster=cluster)
    except Exception:
        logger.exception("could not clear memory for %s", user_id)
