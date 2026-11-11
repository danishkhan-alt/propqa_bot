"""A recorded chat writes the sidebar row and the conversation row together."""

from __future__ import annotations

from common.session.chat_store import record_chat_session, remove_chat_session, transfer_chat_session


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows=None) -> None:
        self.statements: list[tuple] = []
        self.committed = 0
        self._rows = rows if rows is not None else [{"session_id": "thread1"}]

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


def test_a_new_message_writes_the_sidebar_and_the_conversation():
    conn = _Conn()
    record_chat_session("user1", "thread1", "Hello there", pool=_Pool(conn))

    sql = [item[0] for item in conn.statements]
    assert "INSERT INTO chat_sessions" in sql[0]
    assert "INSERT INTO conversation_sessions" in sql[1]
    assert "OFFSET %s" in sql[2]
    assert conn.committed == 1


def test_a_session_owned_by_someone_else_does_not_gain_a_turn():
    conn = _Conn(rows=[])
    record_chat_session("user1", "thread1", "Hello", pool=_Pool(conn))

    assert len(conn.statements) == 1
    assert "conversation_sessions" not in conn.statements[0][0]


def test_forget_removes_both_session_rows():
    conn = _Conn()
    assert remove_chat_session("thread1", pool=_Pool(conn)) == "thread1"

    sql = [item[0] for item in conn.statements]
    assert "DELETE FROM chat_sessions" in sql[0]
    assert "DELETE FROM conversation_sessions" in sql[1]
    assert remove_chat_session("has spaces", pool=_Pool(conn)) is None


def test_transfer_updates_the_owner_only_when_it_matches():
    conn = _Conn()
    assert transfer_chat_session("thread1", "user1", "user2", pool=_Pool(conn)) is True

    update = conn.statements[0][0]
    assert "SET user_id = %s" in update
    assert "title" not in update.lower()
    assert conn.statements[0][1] == ("user2", "thread1", "user1")

    missed = _Conn(rows=[])
    assert transfer_chat_session("thread1", "user1", "user2", pool=_Pool(missed)) is False
