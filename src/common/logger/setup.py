from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from common.logger.app_logger import JsonFormatter
from common.logger.category_filter import CategoryFilter


def configure_logging(
    *,
    level: str = "INFO",
    log_to_file: bool = False,
    logs_dir: str = "logs",
    max_bytes: int = 100 * 1024 * 1024,
    backup_count: int = 10,
) -> None:
    """JSON logs to stderr, and optionally rotating files per category."""

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)

    if not log_to_file:
        return

    Path(logs_dir).mkdir(parents=True, exist_ok=True)

    combined = RotatingFileHandler(
        Path(logs_dir) / "combined.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    combined.setFormatter(JsonFormatter())
    root.addHandler(combined)

    for category in ("app", "agent", "chat", "sessions", "auth", "common"):
        handler = RotatingFileHandler(
            Path(logs_dir) / f"{category}.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        handler.setFormatter(JsonFormatter())
        handler.addFilter(CategoryFilter([category]))
        root.addHandler(handler)
