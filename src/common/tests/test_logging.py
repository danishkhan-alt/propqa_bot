from __future__ import annotations

import json
import logging

from common.context import request_id_var, subject_id_var, user_kind_var
from common.enums.user_kind import UserKind
from common.logger.app_logger import JsonFormatter, get_logger
from common.logger.category_filter import CategoryFilter
from common.logger.redact import redact_headers, redact_token
from common.middleware.request_id import request_id_var as middleware_var


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


def test_category_filter_routes_by_prefix():
    filter_ = CategoryFilter(["agent"])
    matching = logging.LogRecord("agent.router", logging.INFO, __file__, 1, "", None, None)
    other = logging.LogRecord("chat.turn", logging.INFO, __file__, 1, "", None, None)

    assert filter_.filter(matching)
    assert not filter_.filter(other)
    assert get_logger("agent.router").name == "agent.router"


def test_a_token_never_appears_whole():
    secret = "sk-ant-" + "a" * 40
    masked = redact_token(secret)
    assert secret not in masked
    assert masked.startswith("sk-a")


def test_short_values_show_nothing():
    assert redact_token("abc123") == "<redacted>"
    assert redact_token("") == "<empty>"


def test_credential_shaped_headers_are_masked():
    masked = redact_headers(
        {
            "Authorization": "Bearer " + "x" * 40,
            "X-Api-Key": "y" * 40,
            "Content-Type": "application/json",
        }
    )
    assert "x" * 40 not in masked["Authorization"]
    assert "y" * 40 not in masked["X-Api-Key"]
    assert masked["Content-Type"] == "application/json"
