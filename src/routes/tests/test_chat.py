"""The chat API streams text, and a listing result is ids only."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent.enums.routing import Intent, Route, TurnKind
from agent.graphs.chat import build_chat_graph
from agent.memory.session.bootstrap import close_memory
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.schemas.sql import SqlDraft
from agent.sql.execute import SqlPage
from app import create_app
from common.cache import MemoryCache, set_cache
from common.enums.user_kind import UserKind
from common.identity import Caller
from routes.chat import chat_rule
from common.ratelimit.rules import CHAT_REGISTERED, CHAT_VISITOR


@pytest.fixture(autouse=True)
def memory_cache():
    backend = MemoryCache()
    set_cache(backend)
    close_memory()
    yield backend
    set_cache(None)
    close_memory()


class _Greeting:
    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.DIRECT_ANSWER,
            turn_kind=TurnKind.NEW,
            confidence=0.9,
            rationale="Greeting.",
        )

    def stream_answer_direct(self, **kwargs):
        yield "Hello "
        yield "there."

    def answer_direct(self, **kwargs) -> str:
        return "unused"


class _HoldGreeting:
    def __init__(self, release: threading.Event, started: threading.Event) -> None:
        self.release = release
        self.started = started

    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.DIRECT_ANSWER,
            turn_kind=TurnKind.NEW,
            confidence=0.9,
            rationale="Greeting.",
        )

    def stream_answer_direct(self, **kwargs):
        yield "Hello "
        self.started.set()
        self.release.wait(timeout=5)
        yield "there."

    def answer_direct(self, **kwargs) -> str:
        return "unused"


class _Listings:
    def __init__(self) -> None:
        self.listing_ids_only = None
        self.answer_rows = None

    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            intent=Intent.LIST,
            confidence=0.9,
            rationale="Show apartments.",
        )

    def route_domain(self, **kwargs) -> DomainRoute:
        return DomainRoute(
            domain_ids=["listings"],
            join_ids=["locations"],
            confidence=0.9,
            rationale="Inventory.",
        )

    def draft_sql(self, **kwargs) -> SqlDraft:
        self.listing_ids_only = kwargs.get("listing_ids_only")
        return SqlDraft(
            sql="SELECT property_id FROM building_property_records",
            purpose="apartments to show",
        )

    def answer_from_sql(self, **kwargs) -> str:
        self.answer_rows = kwargs["rows"]
        return "Here are 2 apartments in Dubai Marina."

    def answer_direct(self, **kwargs) -> str:
        return "hi"

    def answer_unavailable(self, **kwargs) -> str:
        return "no"


def _rows(sql: str) -> SqlPage:
    del sql
    return SqlPage(
        columns=["property_id", "project_name_en"],
        rows=[
            {"property_id": 15802, "project_name_en": "Marina Gate"},
            {"property_id": "19806", "project_name_en": "Marina Gate"},
        ],
        truncated=False,
        duration_ms=1,
    )


def _client(models, runner=None):
    graph = build_chat_graph(InMemorySaver())
    app = create_app(graph=graph, models=models, sql_runner=runner)
    return TestClient(app), graph


def _http_scope() -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat",
        "raw_path": b"/api/chat",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }


def _header(headers: dict, name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    raise KeyError(name)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        name = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if data:
            events.append((name, json.loads(data)))
    return events


def _read(client: TestClient, message: str, thread_id: str | None = None) -> tuple[int, dict, str]:
    payload = {"message": message}
    if thread_id:
        payload["thread_id"] = thread_id
    with client.stream("POST", "/api/chat", json=payload) as response:
        return response.status_code, dict(response.headers), "".join(response.iter_text())


def test_a_greeting_streams_each_text_piece_then_done():
    client, graph = _client(_Greeting())
    with client:
        status, headers, body = _read(client, "Hi")
        assert status == 200
        assert _header(headers, "content-type").startswith("text/event-stream")
        thread_id = _header(headers, "x-thread-id")
    events = _parse_sse(body)
    assert [event for event, _ in events] == ["text", "text", "done"]
    assert events[0][1] == {"delta": "Hello "}
    assert events[1][1] == {"delta": "there."}
    assert events[2][1]["thread_id"] == thread_id
    assert events[2][1]["route"] == "direct_answer"
    assert events[2][1]["paused"] is False
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    assert state.values["messages"][-1].content == "Hello there."


def test_the_first_text_piece_is_sent_before_the_reply_finishes():
    release = threading.Event()
    started = threading.Event()
    arrived = threading.Event()
    sent_early = threading.Event()
    app = create_app(graph=build_chat_graph(InMemorySaver()), models=_HoldGreeting(release, started))
    payload = b'{"message":"Hi"}'
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    async def send(message):
        raw = message.get("body") or b""
        if b"Hello " in raw:
            arrived.set()

    def watch() -> None:
        if started.wait(timeout=3) and arrived.wait(timeout=3):
            sent_early.set()
        release.set()

    watcher = threading.Thread(target=watch)
    watcher.start()
    asyncio.run(app(_http_scope(), receive, send))
    watcher.join(timeout=3)
    assert sent_early.is_set()


def test_a_listing_reply_streams_ids_and_not_the_row():
    models = _Listings()
    client, graph = _client(models, _rows)
    with client:
        status, headers, body = _read(client, "Show me apartments in Dubai Marina")
        assert status == 200
        thread_id = _header(headers, "x-thread-id")
    events = _parse_sse(body)
    names = [name for name, _ in events]
    assert names.index("listings") < names.index("text")
    listings = next(payload for name, payload in events if name == "listings")
    assert listings == {"ids": ["15802", "19806"]}
    assert "Marina Gate" not in body
    assert "project_name_en" not in body
    assert models.listing_ids_only is True
    assert models.answer_rows == [{"property_id": "15802"}, {"property_id": "19806"}]
    text = "".join(payload["delta"] for name, payload in events if name == "text")
    assert text == "Here are 2 apartments in Dubai Marina."
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    assert state.values["last_need_db"].result_meta["ids"] == ["15802", "19806"]
    assert state.values["listing_ids"] == []


def test_a_second_message_continues_the_same_thread():
    client, graph = _client(_Greeting())
    with client:
        _status, headers, _body = _read(client, "Hi")
        thread_id = _header(headers, "x-thread-id")
        _read(client, "Hello again", thread_id)
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    human = [message for message in state.values["messages"] if message.type == "human"]
    assert [message.content for message in human] == ["Hi", "Hello again"]


def test_a_blank_message_is_rejected():
    client, _graph = _client(_Greeting())
    with client:
        response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 422


def test_chat_uses_the_chat_limit(memory_cache: MemoryCache):
    assert chat_rule(Caller(UserKind.REGISTERED, "user-1")) is CHAT_REGISTERED
    assert chat_rule(Caller(UserKind.VISITOR, "visitor-1")) is CHAT_VISITOR
    client, _graph = _client(_Greeting())
    with client:
        for _ in range(20):
            status, _headers, _body = _read(client, "Hi")
            assert status == 200
        blocked = client.post("/api/chat", json={"message": "Hi"})
    assert blocked.status_code == 429
    keys = list(memory_cache._store)
    assert any("chat.visitor" in key for key in keys)
    assert not any("api.visitor" in key for key in keys)
