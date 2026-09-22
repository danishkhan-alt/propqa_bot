from __future__ import annotations

from langchain_core.messages import BaseMessage


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part)
    return str(content)


def latest_user_text(messages: list) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "human":
            return message_text(message)
    if not messages:
        return ""
    return message_text(messages[-1])


def history_summary(messages: list, *, limit: int = 4) -> str:
    """Short prior-turn text for the routers. Excludes the current message."""
    prior = messages[:-1] if messages else []
    lines: list[str] = []
    for message in prior[-limit:]:
        text = message_text(message).strip().replace("\n", " ")
        if not text:
            continue
        lines.append(f"{message.type}: {text[:500]}")
    return "\n".join(lines)
