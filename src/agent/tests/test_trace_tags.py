"""A turn's trace carries the prompt hash, route, domains, and whether a fallback fired."""

from __future__ import annotations

from agent.enums.routing import Intent, Route, TurnKind
from agent.schemas.routes import DomainRoute, QueryRoute
from agent.services.prompt_version import prompt_version
from agent.services.trace_tags import tag_turn_span, turn_trace_metadata
from agent.services.tracing import write_answer_grounding, write_user_feedback


class _Span:
    def __init__(self) -> None:
        self.metadata = None

    def update(self, *, metadata=None, **kwargs):
        self.metadata = metadata


class _Scores:
    def __init__(self) -> None:
        self.calls = []
        self.flushed = False

    def create_score(self, **kwargs):
        self.calls.append(kwargs)

    def flush(self) -> None:
        self.flushed = True


def test_prompt_version_is_a_short_stable_hash():
    first = prompt_version()
    assert first == prompt_version()
    assert len(first) == 12
    assert int(first, 16) >= 0


def test_the_span_is_tagged_with_the_turn():
    values = {
        "query_route": QueryRoute(
            route=Route.NEED_DB,
            turn_kind=TurnKind.NEW,
            intent=Intent.LIST,
            confidence=0.9,
            rationale="Listings.",
        ),
        "domain_route": DomainRoute(
            domain_ids=["listings", "locations"],
            confidence=0.8,
            rationale="Listings in a place.",
        ),
    }
    span = _Span()
    tag_turn_span(span, values, fallback_fired=True)
    assert span.metadata["prompt_version"] == prompt_version()
    assert span.metadata["route"] == "need_db"
    assert span.metadata["domain_ids"] == ["listings", "locations"]
    assert span.metadata["fallback_fired"] is True
    assert set(turn_trace_metadata(values, fallback_fired=False)) == {
        "prompt_version",
        "route",
        "domain_ids",
        "fallback_fired",
    }


def test_a_thumbs_vote_writes_user_feedback():
    client = _Scores()
    write_user_feedback(client, "trace-9", "up", "helpful")
    write_user_feedback(client, None, "down")
    assert client.calls == [
        {
            "name": "user_feedback",
            "value": 1.0,
            "trace_id": "trace-9",
            "score_id": "user_feedback:trace-9",
            "data_type": "NUMERIC",
            "comment": "helpful",
        }
    ]
    assert client.flushed is True
    write_user_feedback(client, "trace-9", "down")
    assert client.calls[-1]["value"] == 0.0
    assert client.calls[-1]["comment"] is None


def test_a_lookup_reply_writes_answer_grounding_without_a_trace_rewrite():
    client = _Scores()
    write_answer_grounding(client, None, ["AED 9 is not in the rows, the listings, the count, the filters, or the visa minimum."])
    assert client.calls == []
    write_answer_grounding(client, "trace-9", [])
    write_answer_grounding(
        client,
        "trace-9",
        ["AED 900,000 is not in the rows, the listings, the count, the filters, or the visa minimum."],
    )
    assert client.calls[0]["name"] == "answer_grounding"
    assert client.calls[0]["value"] == 1.0
    assert client.calls[0]["score_id"] == "answer_grounding:trace-9"
    assert client.calls[0]["comment"] is None
    assert client.calls[1]["value"] == 0.0
    assert "AED 900,000" in client.calls[1]["comment"]
    assert client.flushed is True
