"""Langfuse client for this process. Missing keys mean traces stay in app logs."""

from __future__ import annotations

import os

from langfuse import get_client

from common.logger import get_logger
from config import ENVIRONMENT, ActiveConfig

logger = get_logger("agent.sql")


def get_langfuse_client():
    """The process Langfuse client, or None when tracing is not configured."""
    if os.environ.get("PYTEST_CURRENT_TEST") or ENVIRONMENT.is_test:
        return None

    if not ActiveConfig.LANGFUSE_PUBLIC_KEY or not ActiveConfig.LANGFUSE_SECRET_KEY:
        return None
    return get_client()
