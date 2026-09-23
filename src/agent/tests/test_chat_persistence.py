from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.checkpointer import delete_thread
from agent.context import AgentContext
from agent.enums.routing import Route, TurnKind
from agent.graphs.chat import build_chat_graph
from agent.schemas.routes import QueryRoute
from config import ActiveConfig


class _DirectModels:
    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.DIRECT_ANSWER,
            turn_kind=TurnKind.NEW,
            confidence=1,
            rationale="greeting",
        )

    def route_domain(self, **kwargs):
        raise AssertionError("a direct answer does not load a domain")

    def answer_direct(self, **kwargs) -> str:
        return "hello"

    def answer_unavailable(self, **kwargs) -> str:
        return "unavailable"


def _invoke(graph, message: str, thread_id: str) -> dict:
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)]},
        config={"configurable": {"thread_id": thread_id, "user_id": "user-1"}},
        context=AgentContext(user_id="user-1", models=_DirectModels()),
        version="v2",
    )
    value = getattr(result, "value", result)
    return value if isinstance(value, dict) else dict(value)


def test_delete_thread_requires_an_id():
    with pytest.raises(ValueError):
        delete_thread("  ")


def test_a_turn_is_written_reloaded_updated_and_deleted():
    thread_id = f"test-{uuid.uuid4()}"
    saver = InMemorySaver()
    graph = build_chat_graph(saver)
    first = _invoke(graph, "Hi", thread_id)

    assert first["user_id"] == "user-1"
    assert [message.content for message in first["messages"]] == ["Hi", "hello"]
    assert first.get("catalog_context", "") == ""

    stored = graph.get_state({"configurable": {"thread_id": thread_id}})
    assert [message.content for message in stored.values["messages"]] == ["Hi", "hello"]

    updated = _invoke(graph, "Thanks", thread_id)
    assert [message.content for message in updated["messages"]] == ["Hi", "hello", "Thanks", "hello"]
    assert graph.get_state({"configurable": {"thread_id": f"{thread_id}-other"}}).values.get("messages") in (
        None,
        [],
    )

    saver.delete_thread(thread_id)
    assert graph.get_state({"configurable": {"thread_id": thread_id}}).values.get("messages") in (None, [])


def _redis_saver():
    if not ActiveConfig.REDIS_URL:
        return None
    try:
        from langgraph.checkpoint.redis import RedisSaver

        saver = RedisSaver(
            redis_url=ActiveConfig.REDIS_URL,
            ttl={"default_ttl": 60 * 24, "refresh_on_read": True},
        )
        saver.setup()
    except Exception:
        return None
    return saver


def test_redis_checkpoint_roundtrip_when_redis_is_up():
    saver = _redis_saver()
    if saver is None:
        pytest.skip("Redis with RediSearch is not available")
    thread_id = f"test-{uuid.uuid4()}"
    try:
        graph = build_chat_graph(saver)
        _invoke(graph, "Hi", thread_id)
        from langgraph.checkpoint.redis import RedisSaver

        fresh = build_chat_graph(RedisSaver(redis_url=ActiveConfig.REDIS_URL))
        stored = fresh.get_state({"configurable": {"thread_id": thread_id}})
        assert [message.content for message in stored.values["messages"]] == ["Hi", "hello"]
        saver.delete_thread(thread_id)
        assert fresh.get_state({"configurable": {"thread_id": thread_id}}).values.get("messages") in (
            None,
            [],
        )
    finally:
        client = getattr(saver, "_redis", None)
        if client is not None:
            client.close()
