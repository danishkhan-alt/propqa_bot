from __future__ import annotations

import asyncio
import uuid

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent.checkpointer import RedisCheckpoint, delete_thread
from agent.context import AgentContext
from agent.enums.routing import Route, TurnKind
from agent.graph.workflow import build_chat_graph
from agent.schemas.routes import (
    Assumptions,
    DomainRoute,
    LastNeedDb,
    QueryRoute,
    as_assumptions,
    as_domain_route,
    as_last_need_db,
    as_query_route,
)
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


def test_async_checkpoint_calls_run_on_the_sync_saver():
    saver = RedisCheckpoint.__new__(RedisCheckpoint)
    calls: list[tuple] = []

    def get_tuple(config):
        calls.append(("get", config))
        return "stored"

    def put(config, checkpoint, metadata, new_versions):
        calls.append(("put", checkpoint))
        return {"configurable": {"thread_id": "t"}}

    def put_writes(config, writes, task_id, task_path=""):
        calls.append(("writes", task_id, task_path, writes))

    def delete_one(thread_id):
        calls.append(("delete", thread_id))

    def list_rows(config, *, filter=None, before=None, limit=None):
        calls.append(("list", limit))
        return iter(["a", "b"])

    saver.get_tuple = get_tuple
    saver.put = put
    saver.put_writes = put_writes
    saver.delete_thread = delete_one
    saver.list = list_rows

    async def exercise() -> None:
        assert await saver.aget_tuple({"configurable": {}}) == "stored"
        stored = await saver.aput({}, "cp", {}, {})
        assert stored == {"configurable": {"thread_id": "t"}}
        await saver.aput_writes({}, [("channel", 1)], "task", "path")
        await saver.adelete_thread("thread-1")
        assert [item async for item in saver.alist(None, limit=2)] == ["a", "b"]

    asyncio.run(exercise())
    assert ("get", {"configurable": {}}) in calls
    assert ("writes", "task", "path", [("channel", 1)]) in calls
    assert ("delete", "thread-1") in calls
    assert ("list", 2) in calls


def test_a_redis_constructor_envelope_reads_back_as_the_model():
    route = as_query_route(
        {
            "lc": 2,
            "type": "constructor",
            "id": ["agent", "schemas", "routes", "QueryRoute"],
            "kwargs": {
                "route": "direct_answer",
                "turn_kind": "new",
                "confidence": 0.99,
                "rationale": "A greeting requires no database lookup.",
            },
        }
    )
    domain = as_domain_route(
        {
            "lc": 2,
            "type": "constructor",
            "id": ["agent", "schemas", "routes", "DomainRoute"],
            "kwargs": {
                "domain_ids": ["listings"],
                "join_ids": ["locations"],
                "confidence": 0.9,
                "rationale": "units",
            },
        }
    )
    assumptions = as_assumptions(
        {
            "lc": 2,
            "type": "constructor",
            "id": ["agent", "schemas", "routes", "Assumptions"],
            "kwargs": {"purpose": "sale", "limit": 10},
        }
    )
    last = as_last_need_db(
        {
            "lc": 2,
            "type": "constructor",
            "id": ["agent", "schemas", "routes", "LastNeedDb"],
            "kwargs": {"domain_ids": ["listings"], "intent_summary": "flats"},
        }
    )

    assert isinstance(route, QueryRoute)
    assert route.route is Route.DIRECT_ANSWER
    assert route.rationale == "A greeting requires no database lookup."
    assert isinstance(domain, DomainRoute)
    assert domain.domain_ids == ["listings"]
    assert isinstance(assumptions, Assumptions)
    assert assumptions.purpose == "sale" and assumptions.limit == 10
    assert isinstance(last, LastNeedDb)
    assert last.intent_summary == "flats"


def test_nested_constructor_envelopes_read_back_as_models():
    route = as_query_route(
        {
            "lc": 2,
            "type": "constructor",
            "id": ["agent", "schemas", "routes", "QueryRoute"],
            "kwargs": {
                "route": "need_db",
                "turn_kind": "new",
                "intent": "list",
                "confidence": 0.95,
                "rationale": "Listings in Dubai Marina under 2M.",
                "names": [
                    {
                        "lc": 2,
                        "type": "constructor",
                        "id": ["agent", "schemas", "listing", "NameMention"],
                        "kwargs": {"text": "dubai marina", "kind": "place"},
                    }
                ],
                "listing_filters": {
                    "lc": 2,
                    "type": "constructor",
                    "id": ["agent", "schemas", "listing", "ListingFilters"],
                    "kwargs": {"purpose": "sale", "price_max": 2000000},
                },
            },
        }
    )

    assert isinstance(route, QueryRoute)
    assert [name.text for name in route.names] == ["dubai marina"]
    assert route.listing_filters is not None
    assert route.listing_filters.price_max == 2000000


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
