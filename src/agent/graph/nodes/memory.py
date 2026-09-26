"""Graph nodes for working memory, recall, refinement, and extraction."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from agent.context import AgentContext
from agent.graph.nodes.runtime import models_for, thread_id_for, user_id_for
from agent.memory.maintenance.privacy import soft_delete_memories
from agent.memory.models.column_map import memory_domains_for
from agent.memory.models.records import clone_frame
from agent.memory.read.personalize import apply_saved_preferences
from agent.memory.read.prompt_text import format_disclosure_line
from agent.memory.read.recall import recall_for_user
from agent.memory.session.backends import get_memory_cache, get_repository
from agent.memory.session.follow_up import derive_search_state_from_message, is_forget_request
from agent.memory.session.working_memory import load_cached_profile, load_working_memory
from agent.schemas.routes import as_query_route
from agent.services.stream_events import publish_stream_event
from agent.services.transcript import latest_user_text
from agent.states.chat import ChatState


def load_session_context(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    """The user id, this chat's working memory, and the user's saved profile."""
    user_id = user_id_for(state, runtime, config)
    update: dict[str, Any] = {"user_id": user_id}
    working = load_working_memory(thread_id_for(config))
    if working:
        update["query_frame"] = working.get("query_frame")
        update["goal"] = working.get("goal")
        update["ignore_defaults"] = bool(working.get("ignore_defaults"))
    profile = load_cached_profile(user_id)
    if profile:
        update["profile"] = profile
    return update


def recall_long_term_memories(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    repository = _memory_repository(runtime)
    query = latest_user_text(state.get("messages") or [])
    recalled = recall_for_user(
        repository,
        user_id_for(state, runtime, config),
        query,
        store=runtime.store if runtime is not None else None,
        memory_cache=get_memory_cache(),
    )
    return recalled


def check_forget_request(state: ChatState) -> dict:
    """A request to forget saved memory stops the turn here, to ask first, before any model runs."""
    message = latest_user_text(state.get("messages") or [])
    if not is_forget_request(message):
        return {"pending_forget": None}
    return derive_search_state_from_message(
        message,
        state.get("query_frame"),
        state.get("goal"),
        ignore_defaults=bool(state.get("ignore_defaults")),
    )


def update_search_frame(
    state: ChatState, runtime: Runtime[AgentContext], config: RunnableConfig
) -> dict:
    """Runs beside choose_query_route: the router does not read the frame, so the follow-up
    classifier's model call overlaps the router's instead of adding to the turn's latency."""
    del config
    message = latest_user_text(state.get("messages") or [])
    update = derive_search_state_from_message(
        message,
        state.get("query_frame"),
        state.get("goal"),
        ignore_defaults=bool(state.get("ignore_defaults")),
        classify=_build_frame_classifier(runtime),
    )
    update["disclosure"] = ""
    update["applied_defaults"] = []
    return update


def ask_before_forgetting_memory(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    pending = state.get("pending_forget") or {}
    answer = interrupt(pending.get("prompt") or "Forget this memory? yes/no")
    if str(answer).strip().lower() in {"yes", "y"}:
        repository = _memory_repository(runtime)
        if repository is not None:
            soft_delete_memories(
                repository,
                user_id_for(state, runtime, config),
                cluster=pending.get("cluster"),
                memory_id=pending.get("memory_id"),
                all_clusters=bool(pending.get("all")),
            )
        text = "Forgot that."
    else:
        text = "Kept your saved preferences."
    publish_stream_event("text", delta=text)
    return {"pending_forget": None, "messages": [AIMessage(content=text)]}


def personalize_search_frame(state: ChatState) -> dict:
    frame = clone_frame(state.get("query_frame"))
    query = as_query_route(state.get("query_route"))
    if query is not None:
        frame["intent"] = query.intent.value
        if query.purpose:
            frame.setdefault("predicates", {})["purpose"] = query.purpose
        if query.limit:
            frame["limit"] = query.limit
    domains = memory_domains_for(state.get("domain_route"))
    frame, labels, block = apply_saved_preferences(
        frame,
        list(state.get("memory_context") or []),
        state.get("profile") or {},
        domains,
        ignore=bool(state.get("ignore_defaults")),
    )
    return {
        "query_frame": frame,
        "memory_block": block,
        "disclosure": format_disclosure_line(labels) if labels else "",
        "applied_defaults": labels,
    }


def queue_memory_extraction(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    memory_cache = get_memory_cache()
    if memory_cache is None:
        return {}
    user_id = user_id_for(state, runtime, config)
    repository = _memory_repository(runtime)
    if (
        repository is not None
        and user_id
        and not repository.get_settings(user_id).memory_enabled
    ):
        return {}
    frame = clone_frame(state.get("query_frame"))
    frame.pop("sql", None)
    meta = dict(frame.get("result_meta") or {})
    meta.pop("sql", None)
    frame["result_meta"] = meta
    messages = state.get("messages") or []
    human = next(
        (
            message
            for message in reversed(messages)
            if getattr(message, "type", None) == "human"
        ),
        None,
    )
    memory_cache.enqueue_extraction_job(
        {
            "user_id": user_id,
            "thread_id": thread_id_for(config),
            "turn": frame.get("turn") or 0,
            "message": latest_user_text(messages),
            "message_id": getattr(human, "id", None),
            "query_frame": frame,
            "result_meta": meta,
            "events": list(state.get("behaviour_events") or []),
        }
    )
    return {}


def next_step_after_forget_check(state: ChatState) -> str | list[str]:
    """Ask before forgetting, or route the query and update the search frame in one step.

    Nodes in one step run concurrently and the next step waits for all of them, so the
    frame is updated before anything that reads it (personalize, reply, memory extraction).
    """
    if state.get("pending_forget"):
        return "ask_before_forgetting_memory"
    return ["choose_query_route", "update_search_frame"]


def _build_frame_classifier(runtime: Runtime[AgentContext] | None):
    """Use Haiku only when this run has a model that knows how to classify a frame."""
    if runtime is None or runtime.context is None:
        return None
    method = getattr(models_for(runtime), "classify_follow_up_kind", None)
    if method is None:
        return None

    def classify(message: str, frame: dict) -> str:
        return method(message=message, frame=frame)

    return classify


def _memory_repository(runtime: Runtime[AgentContext] | None):
    store = runtime.store if runtime is not None else None
    if store is not None and getattr(store, "repository", None) is not None:
        return store.repository
    return get_repository()
