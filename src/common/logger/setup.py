from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from common.logger.app_logger import JsonFormatter


def configure_logging(
    *,
    level: str = "INFO",
    log_to_file: bool = False,
    logs_dir: str = "logs",
    max_bytes: int = 100 * 1024 * 1024,
    backup_count: int = 10,
) -> None:
    """JSON logs to stderr, and optionally one rotating file.

    Each line carries a `category` field, so filter on that instead of splitting files.
    """

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    stream = logging.StreamHandler()
    stream.setFormatter(JsonFormatter())
    root.addHandler(stream)

    if not log_to_file:
        return

    Path(logs_dir).mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        Path(logs_dir) / "app.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    file_handler.setFormatter(JsonFormatter())
    root.addHandler(file_handler)
