"""Legacy public accounts are copied into the chat schema only when they are new."""

from __future__ import annotations

from auth.storage.postgres import copy_public_accounts


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, responses: list[list]) -> None:
        self.responses = list(responses)
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        rows = self.responses.pop(0) if self.responses else []
        return _Result(rows)


def test_a_missing_public_table_is_left_alone():
    conn = _Conn([[{"reg": None}]])

    copy_public_accounts(conn)

    assert len(conn.statements) == 1
    assert "to_regclass" in conn.statements[0]


def test_public_tokens_map_a_boolean_revoked_flag():
    conn = _Conn(
        [
            [{"reg": "public.chatbot_users"}],
            [],
            [{"reg": "public.chatbot_refresh_tokens"}],
            [{"column_name": "revoked"}],
            [],
        ]
    )

    copy_public_accounts(conn)

    assert "INSERT INTO chatbot_users" in conn.statements[1]
    assert "is_verified" not in conn.statements[1]
    assert "CASE WHEN p.revoked THEN p.created_at ELSE NULL END" in conn.statements[4]
    assert "public.chatbot_refresh_tokens" in conn.statements[4]
