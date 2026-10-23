"""History order and follow-up context must respect the scope of each turn."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from backend.resource_store import ResourceStore
from backend.contracts import ChatRequest
from pydantic import ValidationError
import pytest


def test_chat_turn_order_does_not_depend_on_random_message_ids(tmp_path):
    store = ResourceStore(tmp_path / "history.db")
    # Force UUIDs to sort the answer before its question in the former query.
    with patch("backend.resource_store.uuid.uuid4", side_effect=[
        SimpleNamespace(hex="z"), SimpleNamespace(hex="a"),
    ]):
        store.append_chat_turn("user", "session", "Question?", "Answer.", ["doc"], [])
    expected = [{"role": "user", "content": "Question?"}, {"role": "assistant", "content": "Answer."}]
    session = store.get_chat_session("session", "user")
    assert [{"role": m["role"], "content": m["content"]} for m in session["messages"]] == expected
    assert store.get_recent_chat_turns("session", "user", source_ids=["doc"]) == expected
    assert store.get_chat_session("session", "other-user") is None
    assert store.get_recent_chat_turns("session", "other-user", source_ids=["doc"]) == []


def test_source_changes_do_not_resurrect_context_from_previous_materials(tmp_path):
    store = ResourceStore(tmp_path / "history.db")
    store.append_chat_turn("user", "session", "A?", "A.", ["a"], [])
    store.append_chat_turn("user", "session", "B?", "B.", ["b"], [])
    assert store.get_recent_chat_turns("session", "user", source_ids=["a"]) == []
    store.append_chat_turn("user", "session", "A again?", "New A.", ["a"], [])
    turns = store.get_recent_chat_turns("session", "user", source_ids=["a"])
    assert [turn["content"] for turn in turns] == ["A again?", "New A."]


def test_video_rewind_excludes_future_conversation_and_restores_saved_cutoff(tmp_path):
    store = ResourceStore(tmp_path / "history.db")
    store.append_chat_turn("user", "session", "Ending?", "Spoiler.", ["video"], [], video_scopes={"video": 120})
    assert store.get_recent_chat_turns("session", "user", source_ids=["video"], video_scopes={"video": 30}) == []
    assert store.get_recent_chat_turns("session", "user", source_ids=["video"], video_scopes={"video": 120})
    assert store.get_chat_session("session", "user")["video_scopes"] == {"video": 120}
    store.append_chat_turn("user", "session", "Beginning?", "Intro.", ["video"], [], video_scopes={"video": 30})
    assert len(store.get_recent_chat_turns("session", "user", source_ids=["video"], video_scopes={"video": 30})) == 2


def test_legacy_history_remains_visible_without_becoming_unscoped_model_context(tmp_path):
    database = tmp_path / "history.db"
    store = ResourceStore(database)
    store.append_chat_turn("user", "session", "Old?", "Old.", ["doc"], [])
    with store._connect() as connection:
        connection.execute("ALTER TABLE chat_messages DROP COLUMN scope_json")
    reopened = ResourceStore(database)
    assert len(reopened.get_chat_session("session", "user")["messages"]) == 2
    assert reopened.get_recent_chat_turns("session", "user", source_ids=["doc"]) == []


def test_scope_order_is_irrelevant_and_context_limit_keeps_complete_pairs(tmp_path):
    store = ResourceStore(tmp_path / "history.db")
    for index in range(8):
        store.append_chat_turn("user", "session", f"Q{index}", f"A{index}", ["a", "b"], [])
    turns = store.get_recent_chat_turns("session", "user", source_ids=["b", "a"], limit=5)
    assert [turn["content"] for turn in turns] == ["Q6", "A6", "Q7", "A7"]
    with store._connect() as connection:
        row = connection.execute("SELECT scope_json FROM chat_messages LIMIT 1").fetchone()
    assert json.loads(row["scope_json"])["source_ids"] == ["a", "b"]


@pytest.mark.parametrize("timestamp", [float("nan"), float("inf"), float("-inf")])
def test_playback_limits_must_be_finite(timestamp):
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s", question="Q?", allowed_source_ids=["v"],
                    video_scopes=[{"source_id": "v", "playback_seconds": timestamp}])
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s", question="Q?", allowed_source_ids=["v"],
                    video_source_id="v", playback_seconds=timestamp)


def test_legacy_and_modern_video_scopes_share_the_same_limit():
    source_ids = [f"v{index}" for index in range(11)]
    with pytest.raises(ValidationError, match="at most 10"):
        ChatRequest(session_id="s", question="Q?", allowed_source_ids=source_ids,
                    video_source_id="v10", playback_seconds=60,
                    video_scopes=[{"source_id": source, "playback_seconds": 60} for source in source_ids[:10]])
