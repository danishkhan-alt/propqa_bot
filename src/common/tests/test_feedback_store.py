"""The vote row is one per session and turn, and a second vote updates it."""

from __future__ import annotations

from common.feedback import DDL, PostgresFeedbackStore, attach_votes


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self) -> None:
        self.statements: list[tuple] = []
        self.committed = 0
        self._rows: list = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return _Result(self._rows)

    def commit(self) -> None:
        self.committed += 1


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def connection(self):
        return self

    def __enter__(self):
        return self.conn

    def __exit__(self, *args):
        return False


def test_the_table_is_created_on_the_chat_store():
    conn = _Conn()
    PostgresFeedbackStore(_Pool(conn)).ensure_schema()
    sql = conn.statements[0][0]
    assert "CREATE TABLE IF NOT EXISTS chat_feedback" in sql
    assert "PRIMARY KEY (session_id, turn_id)" in sql
    assert conn.committed == 1
    assert DDL == sql or sql in DDL


def test_a_second_vote_updates_the_same_row():
    conn = _Conn()
    store = PostgresFeedbackStore(_Pool(conn))
    store.save(session_id="sess", turn_id="turn", thumbs="up", comment=None, trace_id="trace-1")
    sql, params = conn.statements[-1]
    assert "ON CONFLICT (session_id, turn_id) DO UPDATE" in sql
    assert params["thumbs"] == "up"
    assert params["trace_id"] == "trace-1"
    assert conn.committed == 1


def test_votes_attach_to_the_matching_turn():
    turns = [{"turn_id": "a"}, {"turn_id": "b"}]
    attach_votes(turns, {"b": "down"})
    assert turns[0]["thumbs_up"] is False
    assert turns[0]["thumbs_down"] is False
    assert turns[1]["thumbs_up"] is False
    assert turns[1]["thumbs_down"] is True
