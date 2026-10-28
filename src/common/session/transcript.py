"""Turns restored from a chat checkpoint.

Each listing reply keeps the ids it showed. The session route turns those ids into cards.
Older checkpoints have no ids on the messages, so the last turn falls back to the last search.
"""

from __future__ import annotations

import uuid


# Stable ids for checkpoints saved before a turn id was written on the message.
_LEGACY_TURN_NAMESPACE = uuid.UUID("b7e2c1a0-4d5e-4f6a-8b9c-0d1e2f3a4b5c")


def legacy_turn_id(index: int, user: str, assistant: str) -> str:
    """The same texts at the same position always restore to the same id."""
    return str(uuid.uuid5(_LEGACY_TURN_NAMESPACE, f"{index}\n{user}\n{assistant}"))


def restore_turns_from_checkpoint(values: dict, *, limit: int) -> tuple[list[dict], list[dict]]:
    stored = _messages(values)
    turns = _pair_messages_into_turns(stored)
    if turns and not any(turn["listing_ids"] for turn in turns):
        fallback = _listing_ids(values)
        if fallback:
            turns[-1]["listing_ids"] = fallback
    if limit > 0:
        turns = turns[-limit:]
        stored = stored[-(limit * 2) :]
    messages = [
        {"role": item["role"], "content": item["content"], "ts": item["ts"]} for item in stored
    ]
    return turns, messages


def resolve_feedback_turn(
    values: dict | None,
    *,
    turn_id: str | None,
    user_message: str | None,
    assistant_message: str | None,
) -> tuple[str, str | None]:
    """The turn a thumbs vote belongs to, and the Langfuse trace id stored on it.

    A stored turn id wins. Older checkpoints have none, so the user and assistant
    text identify the same turn the session restore would.
    """
    turns, _messages = restore_turns_from_checkpoint(values or {}, limit=0)
    wanted = (turn_id or "").strip()
    user = (user_message or "").strip()
    assistant = (assistant_message or "").strip()
    if wanted:
        for turn in turns:
            if turn["turn_id"] == wanted:
                return turn["turn_id"], _clean_trace_id(turn.get("trace_id"))
    if user and assistant:
        for turn in reversed(turns):
            if turn["user_message"].strip() == user and turn["assistant_message"].strip() == assistant:
                return turn["turn_id"], _clean_trace_id(turn.get("trace_id"))
    if wanted:
        return wanted, None
    if user or assistant:
        return legacy_turn_id(0, user, assistant), None
    return "", None


def _messages(values: dict) -> list[dict]:
    messages = []
    for item in list(values.get("messages") or []):
        role, content = _message_parts(item)
        if role is None or not content:
            continue
        row = {"role": role, "content": content, "ts": None}
        if role == "assistant":
            ids = _message_listing_ids(item)
            if ids:
                row["listing_ids"] = ids
            turn_id = _message_text(item, "turn_id")
            if turn_id:
                row["turn_id"] = turn_id
            trace_id = _message_text(item, "trace_id")
            if trace_id:
                row["trace_id"] = trace_id
        messages.append(row)
    return messages


def _pair_messages_into_turns(messages: list[dict]) -> list[dict]:
    turns: list[dict] = []
    pending: str | None = None
    index = 0
    for item in messages:
        if item["role"] == "user":
            pending = item["content"]
            continue
        if item["role"] != "assistant" or pending is None:
            continue
        stored = item.get("turn_id")
        turn_id = stored.strip() if isinstance(stored, str) and stored.strip() else ""
        turns.append(
            {
                "turn_id": turn_id or legacy_turn_id(index, pending, item["content"]),
                "ts": None,
                "user_message": pending,
                "assistant_message": item["content"],
                "cards": [],
                "envelope": None,
                "listing_ids": list(item.get("listing_ids") or []),
                "trace_id": item.get("trace_id"),
            }
        )
        pending = None
        index += 1
    return turns


def _listing_ids(values: dict) -> list[str]:
    need = values.get("last_need_db")
    meta = getattr(need, "result_meta", None)
    if meta is None and isinstance(need, dict):
        meta = need.get("result_meta")
    if not isinstance(meta, dict):
        return []
    return [str(item) for item in (meta.get("ids") or []) if str(item).strip()]


def _message_listing_ids(item: object) -> list[str]:
    raw = _additional_kwargs(item).get("listing_ids")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if str(value).strip()]


def _message_text(item: object, name: str) -> str:
    raw = _additional_kwargs(item).get(name)
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def _additional_kwargs(item: object) -> dict:
    kwargs = getattr(item, "additional_kwargs", None)
    if isinstance(kwargs, dict):
        return kwargs
    if isinstance(item, dict):
        kwargs = item.get("additional_kwargs")
        if isinstance(kwargs, dict):
            return kwargs
        data = item.get("data")
        if isinstance(data, dict):
            nested = data.get("additional_kwargs")
            if isinstance(nested, dict):
                return nested
        wrapped = item.get("kwargs")
        if isinstance(wrapped, dict):
            nested = wrapped.get("additional_kwargs")
            if isinstance(nested, dict):
                return nested
    return {}


def _clean_trace_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _message_parts(item: object) -> tuple[str | None, str]:
    role = getattr(item, "type", None)
    if role is None and isinstance(item, dict):
        role = item.get("type") or item.get("role")
    content = getattr(item, "content", None)
    if content is None and isinstance(item, dict):
        content = item.get("content")
    text = _text(content)
    if role in ("human", "user"):
        return "user", text
    if role in ("ai", "assistant"):
        return "assistant", text
    return None, text


def _text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for piece in content:
            if isinstance(piece, str):
                parts.append(piece)
            elif isinstance(piece, dict) and isinstance(piece.get("text"), str):
                parts.append(piece["text"])
        return "".join(parts).strip()
    return ""
