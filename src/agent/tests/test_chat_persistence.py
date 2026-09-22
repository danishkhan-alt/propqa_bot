from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver

from agent.checkpointer import close_checkpointer, delete_thread, get_checkpointer
from agent.context import AgentContext
from agent.enums.routing import Route, TurnKind
from agent.graphs.chat import build_chat_graph
from agent.schemas.routes import QueryRoute
from common.db import chat_conninfo, get_pool


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


def _postgres_ready() -> bool:
    try:
        import psycopg

        with psycopg.connect(chat_conninfo(), connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        return False
    return True


def test_delete_thread_requires_an_id():
    with pytest.raises(ValueError):
        delete_thread("  ")


@pytest.fixture
def thread_id():
    identifier = f"test-{uuid.uuid4()}"
    yield identifier
    delete_thread(identifier)
    close_checkpointer()


def _invoke(graph, message: str, thread_id: str) -> dict:
    result = graph.invoke(
        {"messages": [HumanMessage(content=message)]},
        config={"configurable": {"thread_id": thread_id, "user_id": "user-1"}},
        context=AgentContext(user_id="user-1", models=_DirectModels()),
        version="v2",
    )
    value = getattr(result, "value", result)
    return value if isinstance(value, dict) else dict(value)


@pytest.mark.skipif(not _postgres_ready(), reason="local chatbot postgres is not running")
def test_a_turn_is_written_reloaded_updated_and_deleted(thread_id):
    graph = build_chat_graph(get_checkpointer())
    first = _invoke(graph, "Hi", thread_id)

    assert first["user_id"] == "user-1"
    assert [message.content for message in first["messages"]] == ["Hi", "hello"]
    assert first.get("catalog_context", "") == ""

    # A second saver on the same pool reads the row Postgres stored.
    fresh = PostgresSaver(get_pool("checkpointer"))
    reloaded = build_chat_graph(fresh)
    stored = reloaded.get_state({"configurable": {"thread_id": thread_id}})
    assert [message.content for message in stored.values["messages"]] == ["Hi", "hello"]

    updated = _invoke(reloaded, "Thanks", thread_id)
    assert [message.content for message in updated["messages"]] == ["Hi", "hello", "Thanks", "hello"]
    assert fresh.get_tuple({"configurable": {"thread_id": f"{thread_id}-other"}}) is None

    delete_thread(thread_id)
    assert fresh.get_tuple({"configurable": {"thread_id": thread_id}}) is None
    assert get_pool("checkpointer") is get_pool("checkpointer")
