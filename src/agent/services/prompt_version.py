"""A short hash of the prompt strings a turn actually sends to the model."""

from __future__ import annotations

import hashlib
from functools import lru_cache


@lru_cache(maxsize=1)
def prompt_version() -> str:
    from agent.prompts.query_router import QUERY_ROUTER_SYSTEM
    from agent.prompts.reply import STRUCTURED_REPLY_SYSTEM
    from agent.prompts.sql import SQL_DRAFT_SYSTEM

    blob = "\n---\n".join((QUERY_ROUTER_SYSTEM, SQL_DRAFT_SYSTEM, STRUCTURED_REPLY_SYSTEM))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
