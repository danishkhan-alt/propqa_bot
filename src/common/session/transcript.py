"""Turns restored from a chat checkpoint.

Each listing reply keeps the ids it showed. The session route turns those ids into cards.
Older checkpoints have no ids on the messages, so the last turn falls back to the last search.
"""

from __future__ import annotations

import uuid


def restore_turns_from_checkpoint(values: dict, *, limit: int) -> tuple[list[dict], list[dict]]:
    stored = _messages(values)
    if limit > 0:
        stored = stored[-(limit * 2) :]
    turns = _pair_messages_into_turns(stored)
    if turns and not any(turn["listing_ids"] for turn in turns):
        fallback = _listing_ids(values)
        if fallback:
            turns[-1]["listing_ids"] = fallback
    messages = [
        {"role": item["role"], "content": item["content"], "ts": item["ts"]} for item in stored
    ]
    return turns, messages


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
        messages.append(row)
    return messages


def _pair_messages_into_turns(messages: list[dict]) -> list[dict]:
    turns: list[dict] = []
    pending: str | None = None
    for item in messages:
        if item["role"] == "user":
            pending = item["content"]
            continue
        if item["role"] != "assistant" or pending is None:
            continue
        turns.append(
            {
                "turn_id": str(uuid.uuid4()),
                "ts": None,
                "user_message": pending,
                "assistant_message": item["content"],
                "cards": [],
                "envelope": None,
                "listing_ids": list(item.get("listing_ids") or []),
            }
        )
        pending = None
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
    kwargs = getattr(item, "additional_kwargs", None)
    if not isinstance(kwargs, dict) and isinstance(item, dict):
        kwargs = item.get("additional_kwargs")
        if not isinstance(kwargs, dict) and isinstance(item.get("data"), dict):
            kwargs = item["data"].get("additional_kwargs")
        if not isinstance(kwargs, dict) and isinstance(item.get("kwargs"), dict):
            kwargs = item["kwargs"].get("additional_kwargs")
    if not isinstance(kwargs, dict):
        return []
    raw = kwargs.get("listing_ids")
    if not isinstance(raw, list):
        return []
    return [str(value) for value in raw if str(value).strip()]


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
