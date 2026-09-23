"""Push one chat event to the caller that is streaming this turn."""

from __future__ import annotations

from typing import Any


def publish(event: str, **fields: Any) -> None:
    """Send `event` if this run is streaming. A normal invoke drops it."""
    from langgraph.config import get_stream_writer

    try:
        get_stream_writer()({"event": event, **fields})
    except (KeyError, RuntimeError):
        return
