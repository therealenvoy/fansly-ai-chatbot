"""Tests for MessageStore — persistent fan message history."""

import pytest
from src.memory.store import MessageStore


@pytest.fixture
def store(tmp_path):
    s = MessageStore(f"sqlite:///{tmp_path}/test.db")
    s.create_table()
    return s


def test_save_and_retrieve_message(store):
    store.save_message("fan1", "creator1", "fan", "hey babe")
    history = store.get_history("fan1", "creator1")
    assert len(history) == 1
    assert history[0]["sender"] == "fan"
    assert history[0]["content"] == "hey babe"


def test_history_is_oldest_first(store):
    store.save_message("fan1", "creator1", "fan", "first")
    store.save_message("fan1", "creator1", "creator", "second")
    store.save_message("fan1", "creator1", "fan", "third")
    history = store.get_history("fan1", "creator1")
    assert [m["content"] for m in history] == ["first", "second", "third"]


def test_history_respects_limit(store):
    for i in range(20):
        store.save_message("fan1", "creator1", "fan", f"msg {i}")
    history = store.get_history("fan1", "creator1", limit=5)
    assert len(history) == 5
    # limit returns most recent, ordered oldest-first of those
    assert history[-1]["content"] == "msg 19"
    assert history[0]["content"] == "msg 15"


def test_history_isolated_per_fan(store):
    store.save_message("fan1", "creator1", "fan", "fan1 message")
    store.save_message("fan2", "creator1", "fan", "fan2 message")
    assert len(store.get_history("fan1", "creator1")) == 1
    assert len(store.get_history("fan2", "creator1")) == 1
    assert store.get_history("fan1", "creator1")[0]["content"] == "fan1 message"


def test_history_isolated_per_creator(store):
    store.save_message("fan1", "creatorA", "fan", "for A")
    store.save_message("fan1", "creatorB", "fan", "for B")
    assert len(store.get_history("fan1", "creatorA")) == 1
    assert len(store.get_history("fan1", "creatorB")) == 1


def test_get_recent_context_format(store):
    store.save_message("fan1", "creator1", "fan", "how are you")
    store.save_message("fan1", "creator1", "creator", "doing great babe")
    ctx = store.get_recent_context("fan1", "creator1")
    assert "Fan: how are you" in ctx
    assert "Creator: doing great babe" in ctx


def test_count_messages(store):
    assert store.count_messages("fan1", "creator1") == 0
    store.save_message("fan1", "creator1", "fan", "one")
    store.save_message("fan1", "creator1", "creator", "two")
    assert store.count_messages("fan1", "creator1") == 2


def test_empty_history_returns_empty_list(store):
    assert store.get_history("nobody", "creator1") == []
    assert store.get_recent_context("nobody", "creator1") == ""
