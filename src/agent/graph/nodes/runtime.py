"""Run-scoped helpers the graph nodes share: the models, the user, and the chat thread."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from agent.context import AgentContext, RouterModels
from agent.services.llm import default_models
from agent.states.chat import ChatState


def models_for(runtime: Runtime[AgentContext]) -> RouterModels:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    if runtime.context.models is not None:
        return runtime.context.models
    return default_models()


def user_id_for(
    state: ChatState,
    runtime: Runtime[AgentContext] | None,
    config: RunnableConfig | None,
) -> str:
    """The run context's user, else the one stored in state or passed in config."""
    if runtime is not None and runtime.context is not None and runtime.context.user_id:
        return runtime.context.user_id
    configurable = (config or {}).get("configurable") or {}
    return str(state.get("user_id") or configurable.get("user_id") or "")


def thread_id_for(config: RunnableConfig | None) -> str:
    configurable = (config or {}).get("configurable") or {}
    return str(configurable.get("thread_id") or "")
