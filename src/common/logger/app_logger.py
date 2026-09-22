from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from common.context import request_id_var, subject_id_var, user_kind_var


class JsonFormatter(logging.Formatter):
    """One JSON object per line, carrying the ambient request context."""

    def format(self, record: logging.LogRecord) -> str:
        kind = user_kind_var.get()
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "category": record.name.split(".")[0],
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_kind": kind.value if kind is not None else None,
            "subject_id": subject_id_var.get(),
        }

        extra_data = getattr(record, "extra_data", None)
        if extra_data:
            log_data["extra_data"] = extra_data
        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
