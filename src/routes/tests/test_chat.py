"""The chat API streams text, and a listing result is cards filled from the listing ids."""

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
from agent.schemas.reply import StructuredReply
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


def _cards(ids: list[int]) -> list[dict]:
    known = {
        15802: {
            "id": 15802,
            "title_en": "Marina Gate 2BR",
            "slug_en": "apartments-for-sale-dubai-marina-15802",
            "purpose": "for_sale",
            "show_price": True,
            "price_min": "1450000.0000",
            "rooms": 2,
            "area": "1120.00",
            "completion_status": "off_plan",
            "building_name": "Marina Gate 1",
            "images": ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"],
            "agency_company": "Blue Keys",
        },
    }
    return [known[item] for item in ids if item in known]


def _client(models, runner=None, loader=_cards):
    graph = build_chat_graph(InMemorySaver())
    app = create_app(graph=graph, models=models, sql_runner=runner, listing_loader=loader)
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
    assert events[0][1] == {"delta": "Hello ", "token": "Hello "}
    assert events[1][1] == {"delta": "there.", "token": "there."}
    assert events[2][1]["thread_id"] == thread_id
    assert events[2][1]["route"] == "direct_answer"
    assert events[2][1]["paused"] is False
    assert events[2][1]["done"] is True
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


def test_a_listing_reply_streams_filled_cards_and_not_the_sql_row():
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
    assert listings["ids"] == ["15802", "19806"]
    first, second = listings["cards"]
    assert first["title_en"] == "Marina Gate 2BR"
    assert first["image_url"] == "https://cdn.test/a.jpg"
    assert first["agency_name"] == "Blue Keys"
    assert first["price_min"] == "1450000.0000"
    assert second == {"id": "19806"}
    # The drafted SQL row never reaches the client. Only vetted card fields do.
    assert "project_name_en" not in body
    assert models.listing_ids_only is True
    assert models.answer_rows[0]["title"] == "Marina Gate 2BR"
    assert models.answer_rows[0]["asking_price_aed"] == 1450000
    assert "images" not in models.answer_rows[0]
    text = "".join(payload["token"] for name, payload in events if name == "text")
    assert text == "Here are 2 apartments in Dubai Marina."
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    assert state.values["last_need_db"].result_meta["ids"] == ["15802", "19806"]
    assert state.values["listing_ids"] == []
    assert state.values["listing_cards"] == []


def test_a_session_id_continues_the_same_thread():
    client, graph = _client(_Greeting())
    session_id = "6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    with client:
        _read_session(client, "Hi", session_id)
        _read_session(client, "Hello again", session_id)
    state = graph.get_state({"configurable": {"thread_id": session_id}})
    human = [message for message in state.values["messages"] if message.type == "human"]
    assert [message.content for message in human] == ["Hi", "Hello again"]


def test_a_session_can_be_listed_and_restored():
    client, _graph = _client(_Greeting())
    user_id = "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    session_id = "6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    with client:
        _read_session(client, "Hi", session_id, user_id)
        listed = client.get("/api/sessions", params={"user_id": user_id})
        restored = client.get(f"/api/sessions/{session_id}/turns")
        health = client.get("/api/health")
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["title"] == "Hi"
    assert sessions[0]["user_turns"] == 1
    assert restored.status_code == 200
    body = restored.json()
    assert body["turns"][0]["user_message"] == "Hi"
    assert body["turns"][0]["assistant_message"] == "Hello there."
    assert health.json()["flags"]["ws_mounted"] is False


def test_preferences_round_trip():
    client, _graph = _client(_Greeting())
    user_id = "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    with client:
        saved = client.post(
            "/api/preferences",
            json={"user_id": user_id, "preferences": {"purpose": "buy"}},
        )
        loaded = client.get("/api/preferences", params={"user_id": user_id})
        deleted = client.delete("/api/preferences", params={"user_id": user_id})
        empty = client.get("/api/preferences", params={"user_id": user_id})
    assert saved.status_code == 200
    assert loaded.json()["preferences"]["purpose"] == "buy"
    assert deleted.status_code == 200
    assert empty.json()["preferences"] is None


def _read_session(
    client: TestClient,
    message: str,
    session_id: str,
    user_id: str | None = None,
) -> None:
    payload = {"message": message, "session_id": session_id}
    if user_id:
        payload["user_id"] = user_id
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        "".join(response.iter_text())


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


class _Advisor(_Listings):
    """Listing turns with a structured reply that streams its text."""

    def __init__(self, signals: dict | None = None, purpose: str | None = "sale") -> None:
        super().__init__()
        self.signals = signals or {}
        self.purpose = purpose
        self.drafts: list[dict] = []

    def route_query(self, **kwargs) -> QueryRoute:
        return QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            intent=Intent.LIST,
            purpose=self.purpose,
            profile=self.signals,
            confidence=0.9,
            rationale="Show apartments.",
        )

    def draft_reply(self, *, on_text, **kwargs) -> StructuredReply:
        self.drafts.append(kwargs)
        on_text("Two homes ")
        on_text("stand out.")
        return StructuredReply(
            intro_text="Two homes stand out.",
            message_type="listing_results",
            suggested_followups=["Show ready homes instead"],
        )


def _reply(events: list[tuple[str, dict]]) -> dict:
    return next(payload for name, payload in events if name == "reply")["reply"]


def test_a_structured_reply_streams_its_text_then_the_reply():
    models = _Advisor()
    client, graph = _client(models, _rows)
    with client:
        _, headers, body = _read(client, "Show me apartments in Dubai Marina")
        thread_id = _header(headers, "x-thread-id")
    events = _parse_sse(body)
    names = [name for name, _ in events]
    assert names.index("listings") < names.index("text") < names.index("reply")
    text = "".join(payload["token"] for name, payload in events if name == "text")
    assert text == "Two homes stand out."
    reply = _reply(events)
    assert reply["intro_text"] == "Two homes stand out."
    assert reply["question"]["id"] == "goal"
    assert [option["id"] for option in reply["question"]["options"]] == ["live", "invest", "both"]
    assert models.drafts[0]["listings"][0]["title"] == "Marina Gate 2BR"
    assert models.drafts[0]["follow_up_question"] == reply["question"]["prompt"]
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    # History keeps the question the user was shown.
    assert state.values["messages"][-1].content.endswith(reply["question"]["prompt"])
    assert state.values["profile_asked"] == ["goal"]


def test_each_question_is_asked_once_and_known_facts_are_skipped():
    models = _Advisor(signals={"goal": "invest", "budget_range": "1m_2m"})
    client, _ = _client(models, _rows)
    with client:
        _, headers, first = _read(client, "Investment apartments in Dubai Marina under 2M")
        thread_id = _header(headers, "x-thread-id")
        models.signals = {}
        _, _, second = _read(client, "Any others?", thread_id)
    first_reply = _reply(_parse_sse(first))
    assert first_reply["question"]["id"] == "timeline"
    assert first_reply["session_profile"] == {"goal": "invest", "budget_range": "1m_2m"}
    second_reply = _reply(_parse_sse(second))
    assert second_reply["question"] is None
    assert second_reply["session_profile"] == {"goal": "invest", "budget_range": "1m_2m"}


def test_a_rental_search_asks_no_buyer_question():
    models = _Advisor(purpose="rent")
    client, _ = _client(models, _rows)
    with client:
        _, _, body = _read(client, "Apartments for rent in Dubai Marina")
    assert _reply(_parse_sse(body))["question"] is None


def test_an_invalid_profile_from_the_client_is_dropped():
    models = _Advisor()
    client, _ = _client(models, _rows)
    with client:
        with client.stream(
            "POST",
            "/api/chat",
            json={
                "message": "Apartments in Dubai Marina",
                "session_profile": {"goal": "live", "budget_range": "cheap", "family_size": 99, "x": 1},
            },
        ) as response:
            body = "".join(response.iter_text())
    reply = _reply(_parse_sse(body))
    assert reply["session_profile"] == {"goal": "live"}
    assert reply["question"]["id"] == "budget_range"


def test_a_follow_up_chip_never_repeats_the_question():
    class _Echo(_Advisor):
        def draft_reply(self, *, on_text, **kwargs) -> StructuredReply:
            on_text("Here they are.")
            return StructuredReply(
                intro_text="Here they are.",
                suggested_followups=["Is this a home for you, or an investment?", "Compare with JVC"],
            )

    client, _ = _client(_Echo(), _rows)
    with client:
        _, _, body = _read(client, "Apartments in Dubai Marina")
    assert _reply(_parse_sse(body))["suggested_followups"] == ["Compare with JVC"]
