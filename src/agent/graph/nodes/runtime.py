"""Run-scoped helpers the graph nodes share."""

from __future__ import annotations

from langgraph.runtime import Runtime

from agent.context import AgentContext, RouterModels
from agent.services.llm import default_models


def models_for(runtime: Runtime[AgentContext]) -> RouterModels:
    if runtime.context is None:
        raise RuntimeError("AgentContext is required")
    if runtime.context.models is not None:
        return runtime.context.models
    return default_models()
