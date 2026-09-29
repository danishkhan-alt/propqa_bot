from __future__ import annotations

import json
import logging

from common.enums.user_kind import UserKind
from common.logger.json_formatter import JsonFormatter
from common.middleware.request_id import request_id_var as middleware_var
from common.request_context import request_id_var, subject_id_var, user_kind_var


def test_middleware_and_formatter_share_one_variable():
    assert middleware_var is request_id_var


def test_formatter_picks_up_ambient_caller_context():
    rid = request_id_var.set("abc123")
    kind = user_kind_var.set(UserKind.VISITOR)
    subject = subject_id_var.set("visitor-1")
    try:
        record = logging.LogRecord("chat.turn", logging.INFO, __file__, 1, "hi", None, None)
        emitted = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(rid)
        user_kind_var.reset(kind)
        subject_id_var.reset(subject)

    assert emitted["request_id"] == "abc123"
    assert emitted["user_kind"] == "visitor"
    assert emitted["subject_id"] == "visitor-1"
    assert emitted["category"] == "chat"
    assert emitted["message"] == "hi"


def test_unserialisable_extras_do_not_break_logging():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hi", None, None)
    record.extra_data = {"when": object()}
    assert "extra_data" in json.loads(JsonFormatter().format(record))

