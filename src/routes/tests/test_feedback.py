"""A thumbs click is stored, and a reload shows it on the same turn."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from agent.enums.routing import Route, TurnKind
from agent.graph.workflow import build_chat_graph
from agent.schemas.routes import QueryRoute
from app import create_app
from common.cache import MemoryCache, set_cache
from common.enums.user_kind import UserKind
from common.feedback import MemoryFeedbackStore
from common.identity import Caller
from common.ratelimit.rules import API_REGISTERED, API_VISITOR
from routes.feedback import feedback_rate_limit_for


@pytest.fixture(autouse=True)
def memory_cache():
    set_cache(MemoryCache())
    yield
    set_cache(None)


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


class _Checkpoint:
    def __init__(self, values: dict) -> None:
        self.values = values

    async def aget_state(self, config):
        return self


SESSION = "6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"


def test_thumbs_use_the_api_ceiling_not_the_chat_bucket():
    assert feedback_rate_limit_for(Caller(UserKind.VISITOR, "visitor-1")) is API_VISITOR
    assert feedback_rate_limit_for(Caller(UserKind.REGISTERED, "user-1")) is API_REGISTERED
    assert feedback_rate_limit_for(None) is API_VISITOR


def test_a_thumbs_vote_is_still_there_after_reload():
    store = MemoryFeedbackStore()
    graph = build_chat_graph(InMemorySaver())
    client = TestClient(create_app(graph=graph, models=_Greeting(), feedback_store=store))
    with client:
        with client.stream("POST", "/api/chat", json={"message": "Hi", "session_id": SESSION}) as response:
            assert response.status_code == 200
            "".join(response.iter_text())
        restored = client.get(f"/api/sessions/{SESSION}/turns")
        turn = restored.json()["turns"][0]
        assert restored.status_code == 200
        assert turn["thumbs_up"] is False
        first_id = turn["turn_id"]
        again = client.get(f"/api/sessions/{SESSION}/turns").json()["turns"][0]
        assert again["turn_id"] == first_id

        voted = client.post(
            "/api/feedback/thumbs",
            json={
                "thumbs": "up",
                "message_id": first_id,
                "session_id": SESSION,
                "comment": None,
                "turn_id": first_id,
                "user_message": "Hi",
                "assistant_message": "Hello there.",
            },
        )
        assert voted.status_code == 200
        assert voted.json()["turn_id"] == first_id
        changed = client.post(
            "/api/feedback/thumbs",
            json={
                "thumbs": "down",
                "message_id": first_id,
                "session_id": SESSION,
                "turn_id": first_id,
                "user_message": "Hi",
                "assistant_message": "Hello there.",
            },
        )
        assert changed.status_code == 200
        reloaded = client.get(f"/api/sessions/{SESSION}/turns").json()["turns"][0]
    assert reloaded["turn_id"] == first_id
    assert reloaded["thumbs_up"] is False
    assert reloaded["thumbs_down"] is True
    assert store.rows[(SESSION, first_id)]["thumbs"] == "down"
    reply = graph.get_state({"configurable": {"thread_id": SESSION}}).values["messages"][-1]
    assert reply.additional_kwargs["turn_id"] == first_id


def test_an_older_turn_matches_on_the_message_text(monkeypatch):
    scored = {}

    def capture(trace_id, thumbs, comment=None):
        scored["trace_id"] = trace_id
        scored["thumbs"] = thumbs
        scored["comment"] = comment

    monkeypatch.setattr("routes.feedback.record_user_feedback", capture)
    values = {
        "messages": [
            {"type": "human", "content": "Marina"},
            {
                "type": "ai",
                "content": "Here you go.",
                "additional_kwargs": {"trace_id": "trace-marina"},
            },
        ]
    }
    store = MemoryFeedbackStore()
    client = TestClient(create_app(graph=_Checkpoint(values), feedback_store=store))
    with client:
        before = client.get(f"/api/sessions/{SESSION}/turns").json()["turns"][0]
        voted = client.post(
            "/api/feedback/thumbs",
            json={
                "thumbs": "up",
                "message_id": "not-stable",
                "session_id": SESSION,
                "comment": "right place",
                "turn_id": "11111111-1111-4111-8111-111111111111",
                "user_message": "Marina",
                "assistant_message": "Here you go.",
            },
        )
        after = client.get(f"/api/sessions/{SESSION}/turns").json()["turns"][0]
    assert voted.status_code == 200
    assert voted.json()["turn_id"] == before["turn_id"]
    assert after["turn_id"] == before["turn_id"]
    assert after["thumbs_up"] is True
    assert after["thumbs_down"] is False
    assert "trace_id" not in after
    assert scored == {"trace_id": "trace-marina", "thumbs": "up", "comment": "right place"}


def test_a_vote_needs_a_session_and_a_turn():
    client = TestClient(create_app(graph=_Checkpoint({"messages": []})))
    with client:
        missing_session = client.post("/api/feedback/thumbs", json={"thumbs": "up"})
        missing_turn = client.post(
            "/api/feedback/thumbs",
            json={"thumbs": "up", "session_id": SESSION},
        )
    assert missing_session.status_code == 422
    assert missing_turn.status_code == 422
