from __future__ import annotations

import json

import httpx
import pytest

from agent.enums.routing import TurnKind
from agent.schemas.routes import DomainRoute, LastNeedDb
from agent.services import jev_domain_router
from agent.services.llm.models import LangChainAgentModels
from agent.services.typesafe import SystemOneClient, TypeSafeError

DOMAINS = [
    {"id": "listings", "name": "Properties", "description": "Listings.", "synonyms": ["for sale"]},
    {"id": "schools", "name": "Schools", "description": "KHDA schools.", "not_for": "Parks (amenities)."},
    {"id": "locations", "name": "Communities", "description": "Geo hierarchy."},
    {"id": "market", "name": "Market", "description": "Indices and community averages."},
]
RECIPES = {"community_rents_by_bedrooms": "Rents in ONE named community."}


def _answers(
    lead: str,
    *,
    combines: float = 0.05,
    place: float = 0.05,
    subject: dict[str, float] | None = None,
    recipe: tuple[str, float] = ("none", 0.99),
) -> dict:
    subject = subject or {}
    answers = {
        "lead": {"type": "choice", "choice": lead, "confidence": 0.9, "probabilities": {lead: 0.95}},
        "combines": {"type": "noul", "noul": combines},
        "place": {"type": "noul", "noul": place},
        "recipe": {"type": "choice", "choice": recipe[0], "probabilities": {recipe[0]: recipe[1]}},
    }
    for domain in DOMAINS:
        answers[f"subject_{domain['id']}"] = {"type": "noul", "noul": subject.get(domain["id"], 0.1)}
    return answers


def _client(handler) -> SystemOneClient:
    return SystemOneClient(
        api_key="test-key", model="jev-latest", timeout_seconds=1, transport=httpx.MockTransport(handler)
    )


def _route(answers: dict, sent: list | None = None, **kwargs) -> DomainRoute:
    def handler(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "jev-1", "answers": answers})

    return jev_domain_router.route_domain(
        _client(handler),
        message=kwargs.get("message", "villas for sale in Mirdif"),
        turn_kind=kwargs.get("turn_kind", TurnKind.NEW),
        last_need_db=kwargs.get("last_need_db"),
        domains=DOMAINS,
        recipes=RECIPES,
    )


def test_one_request_asks_every_question_with_catalog_criteria():
    sent: list = []
    last = LastNeedDb(domain_ids=["market"], intent_summary="Rents in JVC")
    _route(_answers("schools"), sent, message="schools there?", turn_kind=TurnKind.PIVOT, last_need_db=last)

    body = sent[0]
    assert body["model"] == "jev-latest"
    assert body["state"] == {
        "message": "schools there?",
        "turn_kind": "pivot",
        "previous_lookup": {"domains": ["market"], "summary": "Rents in JVC"},
    }
    questions = body["questions"]
    assert set(questions) == {"lead", "combines", "place", "recipe"} | {f"subject_{d['id']}" for d in DOMAINS}
    assert set(questions["lead"]["criteria"]) == {"listings", "schools", "locations", "market"}
    assert questions["lead"]["criteria"]["schools"]["not_for"] == "Parks (amenities)."
    assert set(questions["recipe"]["criteria"]) == {"community_rents_by_bedrooms", "none"}


def test_single_subject_ignores_high_subject_scores_without_the_gate():
    route = _route(_answers("listings", combines=0.2, subject={"listings": 0.9, "market": 0.8}))
    assert route.domain_ids == ["listings"]


def test_combined_subjects_add_the_strongest_other_pack():
    route = _route(
        _answers("listings", combines=0.8, place=0.9, subject={"listings": 0.9, "schools": 0.7, "market": 0.45})
    )
    assert route.domain_ids == ["listings", "schools"]
    assert route.join_ids == ["locations"]


def test_combined_gate_without_a_strong_second_pack_keeps_one():
    route = _route(_answers("listings", combines=0.7, subject={"schools": 0.3}))
    assert route.domain_ids == ["listings"]


def test_place_joins_locations_unless_it_is_the_lead():
    assert _route(_answers("schools", place=0.9)).join_ids == ["locations"]
    assert _route(_answers("schools", place=0.2)).join_ids == []
    assert _route(_answers("locations", place=0.95)).join_ids == []


def test_recipe_needs_a_confident_pick():
    confident = _route(_answers("market", recipe=("community_rents_by_bedrooms", 0.98)))
    assert confident.recipe_id == "community_rents_by_bedrooms"
    near_miss = _route(_answers("listings", recipe=("community_rents_by_bedrooms", 0.55)))
    assert near_miss.recipe_id is None


def test_lead_outside_the_catalog_is_an_error():
    with pytest.raises(TypeSafeError):
        _route(_answers("courts"))


def test_client_retries_overload_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["authorization"])
        if len(calls) == 1:
            return httpx.Response(529, json={"detail": "overloaded"})
        return httpx.Response(200, json={"answers": {"q": {"type": "noul", "noul": 0.9}}})

    answers = _client(handler).ask(state="x", questions={"q": {"type": "noul", "instructions": "?"}}, run_name="t")
    assert answers["q"]["noul"] == 0.9
    assert calls == ["Bearer test-key", "Bearer test-key"]


def test_client_does_not_retry_a_rejected_request():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"detail": "bad key"})

    with pytest.raises(TypeSafeError):
        _client(handler).ask(state="x", questions={"q": {"type": "noul", "instructions": "?"}}, run_name="t")
    assert len(calls) == 1


def test_client_rejects_missing_answers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {}})

    with pytest.raises(TypeSafeError):
        _client(handler).ask(state="x", questions={"q": {"type": "noul", "instructions": "?"}}, run_name="t")


def test_router_models_fall_back_to_the_router_model_when_jev_fails():
    class RouterModelDomain:
        def invoke(self, messages, config=None):
            return {"parsed": DomainRoute(domain_ids=["market"], confidence=0.8, rationale="llm")}

    models = LangChainAgentModels.__new__(LangChainAgentModels)
    models._jev = _client(lambda request: httpx.Response(500, text="boom"))
    models._domain = RouterModelDomain()

    route = models.route_domain(
        message="rents in JVC", turn_kind=TurnKind.NEW, last_need_db=None, index_text="", recipes_text=""
    )
    assert route.domain_ids == ["market"]
    assert route.rationale == "llm"
