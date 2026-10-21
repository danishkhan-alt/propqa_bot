"""A session is a sidebar row plus the turns restored from its checkpoint."""

from __future__ import annotations

from common.session import (
    list_user_sessions,
    record_session_activity,
    remove_sidebar_session,
    restore_turns_from_checkpoint,
)
from common.session.preferences import clear, load, merge


def test_a_chat_is_listed_under_its_owner():
    user_id = "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    session_id = "6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    record_session_activity(user_id, session_id, "Hi there")
    record_session_activity(user_id, session_id, "Still here")

    rows = list_user_sessions(user_id)
    assert len(rows) == 1
    assert rows[0].session_id == session_id
    assert rows[0].title == "Hi there"
    assert rows[0].user_turns == 2
    assert list_user_sessions("not a user") == []


def test_detaching_a_session_removes_it_from_the_sidebar():
    user_id = "user1"
    record_session_activity(user_id, "thread1", "Hello")
    assert remove_sidebar_session("thread1") == "thread1"
    assert list_user_sessions(user_id) == []
    assert remove_sidebar_session("has spaces") is None


def test_each_reply_keeps_the_listing_ids_it_showed():
    values = {
        "messages": [
            {"type": "human", "content": "Marina"},
            {
                "type": "ai",
                "content": "Two in Marina.",
                "additional_kwargs": {"listing_ids": ["1", "2"]},
            },
            {"type": "human", "content": "JVC"},
            {
                "type": "ai",
                "content": "One in JVC.",
                "data": {"additional_kwargs": {"listing_ids": ["3"]}},
            },
        ],
        "last_need_db": {"result_meta": {"ids": ["99"]}},
    }
    turns, messages = restore_turns_from_checkpoint(values, limit=30)
    assert [turn["listing_ids"] for turn in turns] == [["1", "2"], ["3"]]
    assert all(turn["cards"] == [] for turn in turns)
    assert all("listing_ids" not in message for message in messages)


def test_an_older_checkpoint_gives_the_last_turn_the_search_ids():
    values = {
        "messages": [
            {"type": "human", "content": "Marina"},
            {"type": "ai", "content": "Here you go."},
            {"type": "human", "content": "Thanks"},
            {"type": "ai", "content": "Anytime."},
        ],
        "last_need_db": {"result_meta": {"ids": ["9", ""]}},
    }
    turns, _messages = restore_turns_from_checkpoint(values, limit=30)
    assert [turn["listing_ids"] for turn in turns] == [[], ["9"]]


def test_preferences_merge_then_clear():
    user_id = "anon-6f1d7c3e-1b4a-4e2d-9c8a-0a1b2c3d4e5f"
    assert load(user_id) is None
    assert merge(user_id, {"purpose": "buy"})["purpose"] == "buy"
    assert merge(user_id, {"beds": 2}) == {"purpose": "buy", "beds": 2}
    clear(user_id)
    assert load(user_id) is None
