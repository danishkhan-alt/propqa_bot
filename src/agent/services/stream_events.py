"""Push one chat event to the caller that is streaming this turn."""

from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer


def publish_stream_event(event: str, **fields: Any) -> None:
    """Send `event` if this run is streaming. A normal invoke drops it."""

    try:
        get_stream_writer()({"event": event, **fields})
    except (KeyError, RuntimeError):
        return
