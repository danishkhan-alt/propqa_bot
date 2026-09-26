"""Domain routing with Jev: each catalog pack is a typed judgment, and code composes the route.

One request asks every question over the same state, so they run in parallel:
- lead: a Choice of the pack that holds the main fact asked for.
- combines: a Noul, whether the message joins two subjects (homes near schools).
- subject_<id>: a Noul per pack, whether it is a subject in its own right. Read only when
  combines holds, to pick the second pack.
- place: a Noul, whether the lookup is limited to a named place (the locations join).
- recipe: a Choice among the fixed lookups, with a none option.
"""

from __future__ import annotations

from typing import Any

from agent.enums.routing import TurnKind
from agent.schemas.routes import DomainRoute, LastNeedDb
from agent.services.typesafe import SystemOneClient, TypeSafeError

# The pack every place-filtered lookup joins through.
JOIN_BRIDGE = "locations"
# Thresholds were set on evals/domain_router_golden.yaml. Per-pack subject scores run high
# for packs merely related to the question, so a second pack also needs the combines gate.
COMBINES_MIN = 0.5
SUBJECT_MIN = 0.4
PLACE_MIN = 0.5
# A recipe skips drafting, so it needs a confident pick; near misses sat around 0.55.
RECIPE_MIN = 0.9
MAX_PRIMARY = 2
NO_RECIPE = "none"

_LEAD = (
    "Which catalog domain holds the main fact the user asks for in `message`? "
    "Match the metric, not the surface noun. When `turn_kind` is pivot, the user keeps the "
    "place from `previous_lookup` and changes the subject; judge the subject `message` asks "
    "about now. If no domain answers exactly, pick the closest one."
)
_SUBJECT = (
    "Does answering `message` need facts from this domain as a subject in its own right? "
    "Count it when the user combines two subjects, such as homes near schools. "
    "Do not count it when it only locates a place for another subject, or when the user "
    "names it only as a word inside another subject's question."
)
_COMBINES = (
    "Does `message` ask for two different kinds of information together, where each needs its "
    "own data, such as homes near schools or apartments near a metro? A place, a developer, a "
    "property type, a period, or a comparison that only narrows or repeats one subject does not "
    "count, and neither does a place carried over from `previous_lookup`."
)
_PLACE = (
    "Is the lookup limited to a named place: a community, area, master community, building, "
    "or project? The place may be named in `message` or carried from `previous_lookup` by a "
    "word such as 'there'. Dubai as a whole is not a place limit."
)
_RECIPE = (
    "Which fixed lookup covers the question in `message` exactly as asked? A recipe fits only "
    "when its condition covers the whole question. Any extra condition it does not allow, such "
    "as a bedroom count, a project, a period, a second place, or a comparison, means none."
)


def route_domain(
    client: SystemOneClient,
    *,
    message: str,
    turn_kind: TurnKind,
    last_need_db: LastNeedDb | None,
    domains: list[dict],
    recipes: dict[str, str],
) -> DomainRoute:
    """Ask Jev and compose the route. Raises TypeSafeError when the answers are unusable."""
    packs = {str(domain["id"]): _pack(domain) for domain in domains}
    questions = build_questions(packs, recipes)
    answers = client.ask(
        state=_state(message, turn_kind, last_need_db),
        questions=questions,
        run_name="router.domain.jev",
    )
    return compose_route(answers, list(packs), recipes)


def build_questions(packs: dict[str, dict], recipes: dict[str, str]) -> dict[str, dict]:
    questions: dict[str, dict] = {
        "lead": {"type": "choice", "instructions": _LEAD, "criteria": packs},
        "combines": {"type": "noul", "instructions": _COMBINES},
        "place": {
            "type": "noul",
            "instructions": _PLACE,
            "criteria": {
                "true": "A community, area, building, or project limits the lookup.",
                "false": "The lookup covers all of Dubai, or names no place.",
            },
        },
    }
    for domain_id, pack in packs.items():
        questions[f"subject_{domain_id}"] = {
            "type": "noul",
            "instructions": {"question": _SUBJECT, "domain": pack},
        }
    if recipes:
        questions["recipe"] = {
            "type": "choice",
            "instructions": _RECIPE,
            "criteria": {**recipes, NO_RECIPE: "No recipe covers the whole question as asked."},
        }
    return questions


def compose_route(answers: dict[str, dict], domain_ids: list[str], recipes: dict[str, str]) -> DomainRoute:
    lead_answer = answers["lead"]
    lead = lead_answer.get("choice")
    if lead not in domain_ids:
        raise TypeSafeError(f"lead {lead!r} is not a catalog domain")

    subject = {domain_id: _noul(answers, f"subject_{domain_id}") for domain_id in domain_ids}
    combines = _noul(answers, "combines")
    seconds: list[str] = []
    if combines >= COMBINES_MIN:
        seconds = sorted(
            (domain_id for domain_id in domain_ids if domain_id != lead and subject[domain_id] >= SUBJECT_MIN),
            key=lambda domain_id: subject[domain_id],
            reverse=True,
        )
    primary = [lead, *seconds][:MAX_PRIMARY]

    place = _noul(answers, "place")
    joins = [JOIN_BRIDGE] if place >= PLACE_MIN and JOIN_BRIDGE in domain_ids and JOIN_BRIDGE not in primary else []

    recipe_id = None
    if recipes:
        recipe_answer = answers["recipe"]
        picked = recipe_answer.get("choice")
        probability = float((recipe_answer.get("probabilities") or {}).get(picked, 0.0))
        if picked in recipes and probability >= RECIPE_MIN:
            recipe_id = picked

    confidence = float(lead_answer.get("confidence") or 0.0)
    rationale = (
        f"Jev lead {lead} ({confidence:.2f}); "
        f"combines {combines:.2f}; seconds {', '.join(f'{d} {subject[d]:.2f}' for d in primary[1:]) or 'none'}; "
        f"place {place:.2f}; recipe {recipe_id or 'none'}."
    )
    return DomainRoute(
        domain_ids=primary,
        join_ids=joins,
        recipe_id=recipe_id,
        confidence=confidence,
        rationale=rationale,
    )


def _pack(domain: dict) -> dict[str, Any]:
    pack: dict[str, Any] = {
        "name": domain.get("name", ""),
        "what": " ".join(str(domain.get("description") or "").split()),
        "covers": list(domain.get("synonyms") or []),
    }
    not_for = " ".join(str(domain.get("not_for") or "").split())
    if not_for:
        pack["not_for"] = not_for
    return pack


def _state(message: str, turn_kind: TurnKind, last: LastNeedDb | None) -> dict[str, Any]:
    previous = None
    if last is not None:
        previous = {"domains": list(last.domain_ids), "summary": last.intent_summary}
    return {"message": message, "turn_kind": turn_kind.value, "previous_lookup": previous}


def _noul(answers: dict[str, dict], question_id: str) -> float:
    value = answers[question_id].get("noul")
    if not isinstance(value, (int, float)):
        raise TypeSafeError(f"{question_id} has no noul")
    return float(value)
