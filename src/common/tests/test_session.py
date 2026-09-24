"""A session is a sidebar row plus the turns restored from its checkpoint."""

from __future__ import annotations

from common.session import detach_session, note_session, sessions_for
from common.session.preferences import clear, load, merge


def test_a_chat_is_listed_under_its_owner():
    user_id = "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    session_id = "6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    note_session(user_id, session_id, "Hi there")
    note_session(user_id, session_id, "Still here")

    rows = sessions_for(user_id)
    assert len(rows) == 1
    assert rows[0].session_id == session_id
    assert rows[0].title == "Hi there"
    assert rows[0].user_turns == 2
    assert sessions_for("not a user") == []


def test_detaching_a_session_removes_it_from_the_sidebar():
    user_id = "user1"
    note_session(user_id, "thread1", "Hello")
    assert detach_session("thread1") == "thread1"
    assert sessions_for(user_id) == []
    assert detach_session("has spaces") is None


def test_preferences_merge_then_clear():
    user_id = "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    assert load(user_id) is None
    assert merge(user_id, {"purpose": "buy"})["purpose"] == "buy"
    assert merge(user_id, {"beds": 2}) == {"purpose": "buy", "beds": 2}
    clear(user_id)
    assert load(user_id) is None
