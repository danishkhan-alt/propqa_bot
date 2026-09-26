"""Graph nodes for working memory, recall, refinement, and extraction."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from agent.context import AgentContext
from agent.memory.read.personalize import apply_saved_preferences
from agent.memory.models.column_map import memory_domains_for
from agent.memory.session.search_results import summarize_search_results
from agent.memory.read.prompt_text import disclosure_line
from agent.memory.maintenance.privacy import forget_memory
from agent.memory.read.recall import recall_for_user
from agent.memory.session.follow_up import update_search_from_message
from agent.memory.session.bootstrap import (
    get_hot,
    get_repository,
    load_profile,
    load_working,
    save_working,
)
from agent.services.events import publish
from agent.memory.models.types import clone_frame
from agent.schemas.routes import as_query_route
from agent.services.transcript import latest_user_text
from agent.states.chat import ChatState


def load_working_memory_and_profile(
    runtime: Runtime[AgentContext] | None, config: RunnableConfig | None
) -> dict:
    user_id = _resolve_user_id({}, runtime, config)
    working = load_working(_thread_id_from_config(config))
    update: dict[str, Any] = {}
    if working:
        update["query_frame"] = working.get("query_frame")
        update["goal"] = working.get("goal")
        update["ignore_defaults"] = bool(working.get("ignore_defaults"))
    profile = load_profile(user_id)
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
        _resolve_user_id(state, runtime, config),
        query,
        store=runtime.store if runtime is not None else None,
        hot=get_hot(),
    )
    return recalled


def update_search_frame(
    state: ChatState, runtime: Runtime[AgentContext], config: RunnableConfig
) -> dict:
    del config
    message = latest_user_text(state.get("messages") or [])
    update = update_search_from_message(
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
            forget_memory(
                repository,
                _resolve_user_id(state, runtime, config),
                cluster=pending.get("cluster"),
                memory_id=pending.get("memory_id"),
                all_clusters=bool(pending.get("all")),
            )
        text = "Forgot that."
    else:
        text = "Kept your saved preferences."
    publish("text", delta=text)
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
        "disclosure": disclosure_line(labels) if labels else "",
        "applied_defaults": labels,
    }


def queue_memory_extraction(
    state: ChatState,
    runtime: Runtime[AgentContext],
    config: RunnableConfig,
) -> dict:
    hot = get_hot()
    if hot is None:
        return {}
    user_id = _resolve_user_id(state, runtime, config)
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
    hot.push(
        {
            "user_id": user_id,
            "thread_id": _thread_id_from_config(config),
            "turn": frame.get("turn") or 0,
            "message": latest_user_text(messages),
            "message_id": getattr(human, "id", None),
            "query_frame": frame,
            "result_meta": meta,
            "events": list(state.get("behaviour_events") or []),
        }
    )
    return {}


def save_working_memory(state: ChatState, config: RunnableConfig | None) -> dict:
    update: dict[str, Any] = {}
    frame = clone_frame(state.get("query_frame")) if state.get("query_frame") else None
    rows = state.get("sql_rows")
    if rows:
        if frame is None:
            frame = clone_frame(None)
        frame["result_meta"] = summarize_search_results(list(rows))
        update["query_frame"] = frame
        update["sql_rows"] = []
    thread_id = _thread_id_from_config(config)
    if thread_id:
        save_working(
            thread_id,
            update.get("query_frame", state.get("query_frame")),
            state.get("goal"),
            bool(state.get("ignore_defaults")),
        )
    return update


def next_step_after_search_frame_update(state: ChatState) -> str:
    if state.get("pending_forget"):
        return "ask_before_forgetting_memory"
    return "choose_query_route"


def _build_frame_classifier(runtime: Runtime[AgentContext] | None):
    """Use Haiku only when this run has a model that knows how to classify a frame."""
    if runtime is None or runtime.context is None:
        return None
    models = runtime.context.models
    if models is None:
        from agent.services.llm import default_models

        models = default_models()
    method = getattr(models, "classify_frame", None)
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


def _resolve_user_id(
    state: ChatState,
    runtime: Runtime[AgentContext] | None,
    config: RunnableConfig | None,
) -> str:
    if runtime is not None and runtime.context is not None and runtime.context.user_id:
        return runtime.context.user_id
    configurable = (config or {}).get("configurable") or {}
    return str(state.get("user_id") or configurable.get("user_id") or "")


def _thread_id_from_config(config: RunnableConfig | None) -> str:
    configurable = (config or {}).get("configurable") or {}
    return str(configurable.get("thread_id") or "")
