"""Follow-up deltas on the working QueryFrame. Comparatives do not need a model."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel

from agent.memory.models.types import clone_frame, empty_frame, utcnow

_FORGET = re.compile(
    r"\b(?:forget|delete)\b.{0,48}\b(?:memor(?:y|ies)|preferences?|defaults|everything|budget|bedrooms?|location)\b",
    re.I,
)
_COMPARATIVE = re.compile(
    r"\b(cheaper|more expensive|pricier|bigger|smaller|newer|older|"
    r"the second one|second one|the third one|the first one|the other(?: one| three)?|"
    r"sort by|with a balcony)\b",
    re.I,
)
_PIVOT = re.compile(
    r"\b(what about|how about|instead|that area|near those|from the metro|how far|the yield|what's the yield|whats the yield)\b",
    re.I,
)
_CARRY = ("location_id_v2", "id")


class FrameClass(BaseModel):
    """Haiku's decision when a follow-up is not one of the known comparatives."""

    kind: Literal["refine", "pivot", "new"]


def update_search_from_message(
    message: str,
    frame: dict[str, Any] | None,
    goal: dict[str, Any] | None,
    *,
    ignore_defaults: bool = False,
    now: datetime | None = None,
    classify=None,
) -> dict[str, Any]:
    moment = now or utcnow()
    text = (message or "").strip()
    lowered = text.lower()
    ignore = ignore_defaults or "ignore my defaults" in lowered or "ignore defaults" in lowered
    if not lowered:
        return {"ignore_defaults": ignore, "pending_forget": None}
    if _FORGET.search(lowered):
        return {
            "ignore_defaults": ignore,
            "pending_forget": forget_target(lowered),
        }
    current = clone_frame(frame) if _has_frame(frame) else None
    kind = _classify(lowered, current)
    if kind == "new" and current is not None and classify is not None:
        kind = _judged_kind(classify, text, current) or kind
    if kind == "refine" and current is not None:
        current = _delta(lowered, current)
        current["turn"] = int(current.get("turn") or 0) + 1
        goal = _touch_goal(goal, moment)
    elif kind == "pivot" and current is not None:
        current = _pivot(current)
        current["turn"] = int(current.get("turn") or 0) + 1
        goal = _touch_goal(goal, moment)
    else:
        if _contradicts_goal(goal, lowered):
            goal = None
        current = empty_frame()
        current["turn"] = 1
    goal = _maybe_goal(lowered, goal, moment)
    return {
        "query_frame": current,
        "goal": goal,
        "ignore_defaults": ignore,
        "pending_forget": None,
    }


def forget_target(text: str) -> dict[str, Any]:
    lowered = text.lower()
    if "everything" in lowered or "all my memory" in lowered or "all memory" in lowered:
        return {
            "cluster": None,
            "memory_id": None,
            "all": True,
            "prompt": "Forget everything I remember about you? yes/no",
        }
    if "property preference" in lowered or "bedroom" in lowered:
        cluster = "property_prefs"
        prompt = "Forget all property preferences? yes/no"
    elif "budget" in lowered or "price" in lowered:
        cluster = "budget"
        prompt = "Forget your saved budget? yes/no"
    elif "location" in lowered or "area" in lowered:
        cluster = "location"
        prompt = "Forget your saved location? yes/no"
    else:
        cluster = None
        prompt = "Forget this memory? yes/no"
    return {"cluster": cluster, "memory_id": None, "all": False, "prompt": prompt}


def _judged_kind(classify, message: str, frame: dict[str, Any]) -> str | None:
    try:
        judged = classify(message, frame)
    except Exception:
        return None
    if judged in {"refine", "pivot", "new"}:
        return judged
    return None


def _has_frame(frame: dict[str, Any] | None) -> bool:
    if not frame:
        return False
    return bool(frame.get("predicates") or frame.get("domain") or frame.get("result_meta") or frame.get("turn"))


def _classify(text: str, frame: dict[str, Any] | None) -> str:
    if frame is None:
        return "new"
    if _COMPARATIVE.search(text):
        return "refine"
    if _PIVOT.search(text):
        return "pivot"
    return "new"


def _delta(text: str, frame: dict[str, Any]) -> dict[str, Any]:
    predicates = frame.setdefault("predicates", {})
    meta = frame.get("result_meta") or {}
    if "cheaper" in text:
        _narrow_price(predicates, meta, ceiling=True)
    elif "more expensive" in text or "pricier" in text:
        _narrow_price(predicates, meta, ceiling=False)
    elif "bigger" in text:
        _shift_bedrooms(predicates, 1)
    elif "smaller" in text:
        _shift_bedrooms(predicates, -1)
    elif "newer" in text:
        frame["order_by"] = [["year", "desc"]]
    elif "older" in text:
        frame["order_by"] = [["year", "asc"]]
    elif "second one" in text:
        _pin_id(predicates, meta, 1)
    elif "third one" in text:
        _pin_id(predicates, meta, 2)
    elif "first one" in text:
        _pin_id(predicates, meta, 0)
    elif "other three" in text:
        ids = list(meta.get("ids") or [])
        if len(ids) > 1:
            predicates["id"] = {"in": ids[1:4]}
    elif re.search(r"\bthe other\b", text):
        ids = list(meta.get("ids") or [])
        if len(ids) > 1:
            predicates["id"] = {"in": ids[1:4]}
    if "sort by yield" in text or "by yield" in text:
        frame["order_by"] = [["rental_yield", "desc"]]
    if "balcony" in text:
        predicates["has_balcony"] = {"eq": True}
    frame["sql"] = ""
    return frame


def _narrow_price(predicates: dict, meta: dict, *, ceiling: bool) -> None:
    if ceiling:
        anchor = meta.get("p25_price")
        if isinstance(anchor, (int, float)) and not isinstance(anchor, bool):
            predicates["price"] = {"lte": anchor}
            return
        current = predicates.get("price")
        if isinstance(current, dict) and isinstance(current.get("lte"), (int, float)):
            predicates["price"] = {"lte": current["lte"] * 0.8}
            return
        if isinstance(meta.get("max_price"), (int, float)):
            predicates["price"] = {"lte": meta["max_price"]}
        return
    anchor = meta.get("max_price")
    if isinstance(anchor, (int, float)) and not isinstance(anchor, bool):
        predicates["price"] = {"gte": anchor}
        return
    current = predicates.get("price")
    if isinstance(current, dict) and isinstance(current.get("gte"), (int, float)):
        predicates["price"] = {"gte": current["gte"] * 1.2}


def _shift_bedrooms(predicates: dict, step: int) -> None:
    current = predicates.get("bedrooms")
    if isinstance(current, dict) and isinstance(current.get("eq"), int):
        predicates["bedrooms"] = {"eq": max(0, current["eq"] + step)}


def _pin_id(predicates: dict, meta: dict, index: int) -> None:
    ids = list(meta.get("ids") or [])
    if len(ids) > index:
        predicates["id"] = {"in": [ids[index]]}


def _pivot(frame: dict[str, Any]) -> dict[str, Any]:
    carried = {}
    for key in _CARRY:
        if key in frame.get("predicates", {}):
            carried[key] = frame["predicates"][key]
    meta = dict(frame.get("result_meta") or {})
    pivoted = empty_frame()
    pivoted["predicates"] = carried
    pivoted["result_meta"] = meta
    pivoted["domain"] = ""
    return pivoted


def _maybe_goal(text: str, goal: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    if re.search(r"\b(investment|invest|buy to let)\b", text):
        return _make_goal("investment_search", now, goal)
    if re.search(r"\b(looking|want|need)\b", text) and re.search(r"\b(to rent|for rent|rental)\b", text):
        return _make_goal("rental_search", now, goal)
    return goal


def _make_goal(kind: str, now: datetime, current: dict[str, Any] | None) -> dict[str, Any]:
    started = (current or {}).get("started_at") if (current or {}).get("type") == kind else now.isoformat()
    return {
        "type": kind,
        "constraints": dict((current or {}).get("constraints") or {}),
        "started_at": started,
        "expires_at": (now + timedelta(days=45)).isoformat(),
    }


def _touch_goal(goal: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    if not goal:
        return goal
    refreshed = dict(goal)
    refreshed["expires_at"] = (now + timedelta(days=45)).isoformat()
    return refreshed


def _contradicts_goal(goal: dict[str, Any] | None, text: str) -> bool:
    if not goal:
        return False
    if goal.get("type") == "investment_search" and re.search(
        r"\b(to live|family home|end user|not an investment)\b", text
    ):
        return True
    return False
