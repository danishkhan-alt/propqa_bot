from __future__ import annotations

from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from agent.context import AgentContext, RouterModels
from agent.graphs.workflow import get_chat_graph
from agent.schemas.routes import as_query_route
from agent.services.tracing import langfuse_client
from common.logger import get_logger

logger = get_logger("agent.router")


def run_turn(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    models: RouterModels | None = None,
    focused_property_ids: list[int] | None = None,
) -> dict:
    """Run one user turn. `thread_id` reloads and updates that chat."""
    client = langfuse_client()
    callbacks = _langfuse_callbacks(client)

    def invoke() -> dict:
        result = get_chat_graph().invoke(
            _build_turn_input(message, focused_property_ids=focused_property_ids),
            config={
                "configurable": {"thread_id": thread_id, "user_id": user_id},
                "callbacks": callbacks,
                "metadata": {"user_id": user_id, "session_id": thread_id},
            },
            context=AgentContext(user_id=user_id, models=models),
            version="v2",
        )
        value = getattr(result, "value", result)
        return value if isinstance(value, dict) else dict(value)

    if client is None:
        return invoke()
    from langfuse import propagate_attributes

    with propagate_attributes(user_id=user_id, session_id=thread_id):
        result = invoke()
    client.flush()
    return result


async def stream_turn(
    message: str,
    *,
    thread_id: str,
    user_id: str,
    models: RouterModels | None = None,
    sql_runner=None,
    listing_loader=None,
    listing_detail_loader=None,
    graph: CompiledStateGraph | None = None,
    session_profile: dict | None = None,
    focused_property_ids: list[int] | None = None,
) -> AsyncIterator[dict]:
    """Yield listing cards and text deltas as the turn runs, then a done event."""
    compiled = graph or get_chat_graph()
    client = langfuse_client()
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "callbacks": _langfuse_callbacks(client),
        "metadata": {"user_id": user_id, "session_id": thread_id},
    }
    context = AgentContext(
        user_id=user_id,
        models=models,
        sql_runner=sql_runner,
        listing_loader=listing_loader,
        listing_detail_loader=listing_detail_loader,
    )

    async def events() -> AsyncIterator[dict]:
        paused_at_start = await _is_waiting_for_user_reply(compiled, config)
        graph_input = (
            Command(resume=message)
            if paused_at_start
            else _build_turn_input(
                message, session_profile=session_profile, focused_property_ids=focused_property_ids
            )
        )
        async for item in compiled.astream(
            graph_input,
            config=config,
            context=context,
            stream_mode=["custom", "updates"],
            version="v2",
        ):
            mode, chunk = _unpack_stream_item(item)
            if mode == "custom" and isinstance(chunk, dict) and chunk.get("event"):
                yield chunk
                continue
            if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
                prompt = _interrupt_prompt_text(chunk["__interrupt__"])
                if prompt:
                    yield {"event": "text", "delta": prompt}
        final = await compiled.aget_state(config)
        values = getattr(final, "values", None) or {}
        query = as_query_route(values.get("query_route"))
        yield {
            "event": "done",
            "thread_id": thread_id,
            "route": query.route.value if query is not None else None,
            "paused": bool(getattr(final, "interrupts", None)),
        }

    if client is None:
        async for event in events():
            yield event
        return
    from langfuse import propagate_attributes

    with propagate_attributes(user_id=user_id, session_id=thread_id):
        async for event in events():
            yield event
    client.flush()


def _build_turn_input(
    message: str,
    *,
    session_profile: dict | None = None,
    focused_property_ids: list[int] | None = None,
) -> dict:
    """A new turn. The picked listings are always set, so a turn without them leaves listing mode."""
    graph_input: dict = {
        "messages": [HumanMessage(content=message)],
        "focused_property_ids": list(focused_property_ids or []),
    }
    if session_profile is not None:
        graph_input["session_profile"] = session_profile
    return graph_input


async def _is_waiting_for_user_reply(graph: CompiledStateGraph, config: dict) -> bool:
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        return False
    return bool(getattr(snapshot, "interrupts", None))


def _unpack_stream_item(item) -> tuple:
    """LangGraph v2 yields `{type, data}`. Older runs yield `(mode, data)`."""
    if isinstance(item, dict) and "type" in item and "data" in item:
        return item["type"], item["data"]
    if isinstance(item, tuple) and len(item) == 3 and isinstance(item[1], str):
        return item[1], item[2]
    if isinstance(item, tuple) and len(item) == 2:
        return item[0], item[1]
    return None, None


def _interrupt_prompt_text(raw) -> str:
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    for item in items:
        value = getattr(item, "value", item)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            prompt = value.get("prompt") or value.get("message")
            if prompt:
                return str(prompt).strip()
    return ""


def _langfuse_callbacks(client) -> list:
    if client is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("langfuse is not installed; router traces stay in app logs")
        return []
    return [CallbackHandler()]
