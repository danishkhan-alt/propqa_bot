from __future__ import annotations

import pytest

from common.db import build_conninfo, chat_conninfo, get_pool
from config import ActiveConfig


def test_conninfo_escapes_credentials():
    info = build_conninfo(
        host="db.internal",
        port=5432,
        dbname="propqa_chatbot",
        user="propqa",
        password="p@ss word",
        sslmode="disable",
    )

    assert "host=db.internal" in info
    assert "port=5432" in info
    assert "dbname=propqa_chatbot" in info
    assert "user=propqa" in info
    assert "sslmode=disable" in info
    assert "password='p@ss word'" in info


def test_pool_name_is_required():
    with pytest.raises(ValueError):
        get_pool("  ")


def test_chat_conninfo_uses_the_chat_database_settings():
    info = chat_conninfo()

    assert f"host={ActiveConfig.CHAT_DB_HOST}" in info
    assert f"dbname={ActiveConfig.CHAT_DB_NAME}" in info
    if ActiveConfig.CHAT_DB_USER:
        assert f"user={ActiveConfig.CHAT_DB_USER}" in info
    if ActiveConfig.CHAT_DB_PASSWORD:
        assert "password=" in info
    else:
        assert "password=" not in info
