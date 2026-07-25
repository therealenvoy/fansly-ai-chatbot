"""Tests for FanslyBot message deduplication (Task 4).

C1 Bug: Bot replies to the same fan message every 30 seconds.
Fix: Track processed message_ids per fan and skip duplicates.

RED phase: Write failing tests first, then implement in bot.py.
GREEN phase: All tests pass after implementation.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.bot import FanslyBot
from src.fansly_client import ApifanslyClient as FanslyClient, FanslyConfig, ChatInfo, MessageInfo
from src.funnel.session import FanSession
from src.notes.models import FanNote


# ─── Helpers ─────────────────────────────────────────────────────


def _make_bot() -> FanslyBot:
    """Create a minimal FanslyBot with mocked dependencies."""
    config = FanslyConfig(api_key="test_key", account_id="test_acc")
    client = FanslyClient(config)
    # Stub out the HTTP client so no real calls happen
    client._client = MagicMock()

    persona_loader = MagicMock()
    persona = MagicMock()
    persona.forbidden_phrases = []
    persona.pet_names = ["babe"]
    persona_loader.load.return_value = persona

    note_repo = MagicMock()
    # Make engine.url renderable as string
    mock_url = MagicMock()
    mock_url.render_as_string.return_value = "sqlite:///:memory:"
    mock_engine = MagicMock()
    mock_engine.url = mock_url
    note_repo.engine = mock_engine

    # Return a real FanNote so comparisons like note.purchase_count > 0 work
    def _get_note(fan_id, creator_id):
        return FanNote(fan_id=fan_id, creator_id=creator_id)
    note_repo.get.side_effect = _get_note

    bot = FanslyBot(
        client=client,
        persona_loader=persona_loader,
        note_repo=note_repo,
        creator_id="test_creator",
    )
    return bot


def _make_chat(fan_id: str = "fan_1", chat_id: str = "chat_1") -> ChatInfo:
    """Create a minimal ChatInfo for testing."""
    return ChatInfo(
        chat_id=chat_id,
        partner_account_id=fan_id,
        partner_username="test_fan",
        partner_display_name="Test Fan",
    )


# ─── RED Phase: Dedup Base Tests ────────────────────────────────


class TestMessageDedupBase:
    """Basic _has_processed / _mark_processed unit tests."""

    def test_initial_state_has_no_processed_messages(self):
        """Fresh bot has no processed messages for any fan."""
        bot = _make_bot()
        assert bot._processed_message_ids == {}

    def test_has_processed_returns_false_for_unknown_fan(self):
        """Unknown fan_id returns False."""
        bot = _make_bot()
        assert bot._has_processed("fan_unknown", "msg_1") is False

    def test_has_processed_returns_false_before_mark(self):
        """Before marking, has_processed returns False."""
        bot = _make_bot()
        bot._mark_processed("fan_1", "msg_1")
        assert bot._has_processed("fan_2", "msg_1") is False

    def test_has_processed_returns_true_after_mark(self):
        """After marking, has_processed returns True for same (fan, msg)."""
        bot = _make_bot()
        bot._mark_processed("fan_1", "msg_1")
        assert bot._has_processed("fan_1", "msg_1") is True

    def test_different_messages_tracked_independently(self):
        """Different message_ids for same fan tracked independently."""
        bot = _make_bot()
        bot._mark_processed("fan_1", "msg_1")
        assert bot._has_processed("fan_1", "msg_2") is False
        bot._mark_processed("fan_1", "msg_2")
        assert bot._has_processed("fan_1", "msg_1") is True
        assert bot._has_processed("fan_1", "msg_2") is True

    def test_different_fans_tracked_independently(self):
        """Same message_id for different fans tracked independently."""
        bot = _make_bot()
        bot._mark_processed("fan_1", "msg_1")
        bot._mark_processed("fan_2", "msg_1")
        assert bot._has_processed("fan_1", "msg_1") is True
        assert bot._has_processed("fan_2", "msg_1") is True
        assert bot._has_processed("fan_1", "msg_2") is False
        assert bot._has_processed("fan_2", "msg_2") is False


class TestMessageDedupEviction:
    """LRU eviction when _processed_message_ids exceeds threshold."""

    def test_no_eviction_below_threshold(self):
        """Many messages for one fan below max_dedup_entries keeps all."""
        bot = _make_bot()
        # Add messages just under threshold
        for i in range(bot._max_dedup_entries - 1):
            bot._mark_processed("fan_1", f"msg_{i}")
        total = sum(len(s) for s in bot._processed_message_ids.values())
        assert total == bot._max_dedup_entries - 1

    def test_eviction_clears_worst_fan_at_threshold(self):
        """At threshold, the fan with most entries gets cleared."""
        bot = _make_bot()
        # Fill fan_1 with max_dedup_entries - 1, fan_2 with 1
        for i in range(bot._max_dedup_entries - 1):
            bot._mark_processed("fan_1", f"msg_{i}")
        bot._mark_processed("fan_2", "msg_single")

        # Total is max_dedup_entries, next add should trigger eviction
        bot._mark_processed("fan_3", "msg_new")

        # fan_1 was the worst (most entries), should be cleared
        assert len(bot._processed_message_ids.get("fan_1", set())) == 0
        # fan_2 and fan_3 should remain
        assert bot._has_processed("fan_2", "msg_single") is True
        assert bot._has_processed("fan_3", "msg_new") is True

    def test_eviction_clears_most_entries_fan(self):
        """Eviction removes the fan with the most entries."""
        bot = _make_bot()
        # fan_1: 5 entries, fan_2: 997 entries (total = 1002)
        for i in range(5):
            bot._mark_processed("fan_1", f"a_{i}")
        for i in range(997):
            bot._mark_processed("fan_2", f"b_{i}")

        # Eviction triggers mid-loop when total > max_dedup_entries.
        # fan_2 (worst) gets cleared, only the last entry (b_996) remains.
        # fan_1 (5 entries) should still be intact.
        assert len(bot._processed_message_ids.get("fan_1", set())) == 5
        # fan_2 should have been cleared — at most 1 entry from post-eviction add
        assert len(bot._processed_message_ids.get("fan_2", set())) <= 1
        assert bot._has_processed("fan_1", "a_0") is True
        assert bot._has_processed("fan_1", "a_4") is True


class TestMessageDedupIntegration:
    """Integration: dedup in _process_chat prevents double-processing."""

    @patch.object(FanslyBot, "_init_purchase_cache")
    def test_same_message_skipped_on_second_call(self, mock_init):
        """Processing the same message twice skips on second call."""
        bot = _make_bot()
        chat = _make_chat()

        # Mock client.list_messages to return the same messages both times
        msg = MessageInfo(
            message_id="msg_1",
            content="Hello!",
            sender_id="fan_1",
            created_at=1000,
            is_from_fan=True,
        )
        bot.client.list_messages = MagicMock(return_value=([msg], None))

        # Mock send_message to track calls
        bot.client.send_message = MagicMock()

        # Mock _generate_reply to return a string
        bot._generate_reply = MagicMock(return_value="Hi there!")

        # First call: should process
        bot._process_chat(chat)
        assert bot._has_processed("fan_1", "msg_1") is True
        # _generate_reply should have been called
        assert bot._generate_reply.called

        # Reset mock and call again
        bot._generate_reply.reset_mock()
        bot._process_chat(chat)
        # _generate_reply should NOT have been called — message was already processed
        assert not bot._generate_reply.called

    @patch.object(FanslyBot, "_init_purchase_cache")
    def test_new_message_is_processed(self, mock_init):
        """A new (different) message_id IS processed even if older ones were seen."""
        bot = _make_bot()
        chat = _make_chat()

        # First call: msg_1
        msg_1 = MessageInfo(
            message_id="msg_1", content="Hi", sender_id="fan_1",
            created_at=1000, is_from_fan=True,
        )
        bot.client.list_messages = MagicMock(return_value=([msg_1], None))
        bot._generate_reply = MagicMock(return_value="Hey!")
        bot._process_chat(chat)
        assert bot._has_processed("fan_1", "msg_1") is True

        # Second call: msg_2 (new message)
        msg_2 = MessageInfo(
            message_id="msg_2", content="How are you?", sender_id="fan_1",
            created_at=1001, is_from_fan=True,
        )
        bot.client.list_messages = MagicMock(return_value=([msg_2], None))
        bot._generate_reply.reset_mock()
        bot._process_chat(chat)
        assert bot._has_processed("fan_1", "msg_2") is True
        assert bot._generate_reply.called

    @patch.object(FanslyBot, "_init_purchase_cache")
    def test_different_fan_not_affected(self, mock_init):
        """Processing fan_1's message doesn't affect fan_2's messages."""
        bot = _make_bot()
        chat_1 = _make_chat(fan_id="fan_1", chat_id="chat_1")
        chat_2 = _make_chat(fan_id="fan_2", chat_id="chat_2")

        msg_1 = MessageInfo(
            message_id="msg_1", content="Hi from fan1", sender_id="fan_1",
            created_at=1000, is_from_fan=True,
        )
        msg_2 = MessageInfo(
            message_id="msg_1", content="Hi from fan2", sender_id="fan_2",
            created_at=1000, is_from_fan=True,
        )

        bot.client.list_messages = MagicMock()
        bot.client.list_messages.side_effect = [([msg_1], None), ([msg_2], None)]
        bot._generate_reply = MagicMock(return_value="Hello!")

        bot._process_chat(chat_1)
        bot._generate_reply.reset_mock()
        bot._process_chat(chat_2)

        # fan_2's msg_1 should NOT be skipped just because fan_1 had a msg_1
        assert bot._generate_reply.called