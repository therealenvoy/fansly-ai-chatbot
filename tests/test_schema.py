"""
Tests for Conversation Schema — 5-Stage Funnel + 5 Personality Types

Strict TDD: RED → GREEN → REFACTOR cycle.
"""

import pytest
from datetime import datetime
from src.schema import (
    ConversationStage,
    PersonalityType,
    Message,
    Conversation,
)


class TestConversationStage:
    """5-stage funnel: RAPPORT, TEASE, OFFER, HANDLE, CLOSE"""

    def test_five_conversation_stages_exist(self):
        """Verify all 5 funnel stages are defined with correct values."""
        assert ConversationStage.RAPPORT.value == "rapport"
        assert ConversationStage.TEASE.value == "tease"
        assert ConversationStage.OFFER.value == "offer"
        assert ConversationStage.HANDLE.value == "handle"
        assert ConversationStage.CLOSE.value == "close"

        # Ensure exactly 5 stages (no more, no less)
        stage_values = {s.value for s in ConversationStage}
        assert stage_values == {"rapport", "tease", "offer", "handle", "close"}

    def test_new_stage_handle_exists(self):
        """HANDLE must exist with value 'handle'."""
        assert hasattr(ConversationStage, "HANDLE")
        assert ConversationStage.HANDLE.value == "handle"


class TestPersonalityType:
    """5 personality types: INSTANT_BUYER, QUIET_LURKER, ATTENTION_SEEKER, TESTER, CHATTY_FAN"""

    def test_five_personality_types_exist(self):
        """Verify all 5 personality types are defined."""
        assert PersonalityType.INSTANT_BUYER.value == "instant_buyer"
        assert PersonalityType.QUIET_LURKER.value == "quiet_lurker"
        assert PersonalityType.ATTENTION_SEEKER.value == "attention_seeker"
        assert PersonalityType.TESTER.value == "tester"
        assert PersonalityType.CHATTY_FAN.value == "chatty_fan"

        # Ensure exactly 5 types
        type_values = {t.value for t in PersonalityType}
        assert type_values == {
            "instant_buyer",
            "quiet_lurker",
            "attention_seeker",
            "tester",
            "chatty_fan",
        }


class TestConversationFunnelProgression:
    """Test the 5-stage funnel flow through a Conversation."""

    def test_conversation_funnel_progression_valid(self):
        """Create Conversation with stages [RAPPORT→TEASE→OFFER→HANDLE→CLOSE] and verify."""
        conv = Conversation(
            conversation_id="conv_test_001",
            subscriber_id="sub_test_123",
            creator_id="creator_test",
            platform="fansly",
            messages=[
                Message(
                    timestamp=datetime.now(),
                    sender="creator",
                    content="Hey there! Welcome to my page! 💕",
                    stage=ConversationStage.RAPPORT,
                    message_length=33,
                    contains_emoji=True,
                ),
                Message(
                    timestamp=datetime.now(),
                    sender="creator",
                    content="I've got something special just for you... 😏",
                    stage=ConversationStage.TEASE,
                    message_length=42,
                    contains_emoji=True,
                ),
                Message(
                    timestamp=datetime.now(),
                    sender="creator",
                    content="Exclusive content bundle — $25 for loyal fans only!",
                    stage=ConversationStage.OFFER,
                    message_length=52,
                ),
                Message(
                    timestamp=datetime.now(),
                    sender="subscriber",
                    content="Hmm, that's kinda expensive...",
                    stage=ConversationStage.HANDLE,
                    message_length=30,
                ),
                Message(
                    timestamp=datetime.now(),
                    sender="creator",
                    content="Done! You're going to love this. 💋",
                    stage=ConversationStage.CLOSE,
                    message_length=38,
                    contains_emoji=True,
                ),
            ],
            total_exchanges=5,
            stages_completed=[
                ConversationStage.RAPPORT,
                ConversationStage.TEASE,
                ConversationStage.OFFER,
                ConversationStage.HANDLE,
                ConversationStage.CLOSE,
            ],
        )

        assert conv.conversation_id == "conv_test_001"
        assert len(conv.messages) == 5
        assert len(conv.stages_completed) == 5

        # Verify correct progression order
        expected_stages = [
            ConversationStage.RAPPORT,
            ConversationStage.TEASE,
            ConversationStage.OFFER,
            ConversationStage.HANDLE,
            ConversationStage.CLOSE,
        ]
        assert conv.stages_completed == expected_stages


class TestMessageModel:
    """Message model — includes new fan_archetype field."""

    def test_message_has_fan_archetype_tag(self):
        """Create Message with fan_archetype='chatty_fan' and verify the field."""
        msg = Message(
            timestamp=datetime.now(),
            sender="subscriber",
            content="OMG I love your content so much!! Can we chat more?? 💕💕",
            fan_archetype="chatty_fan",
            message_length=56,
            contains_emoji=True,
        )

        assert msg.fan_archetype == "chatty_fan"
        assert msg.sender == "subscriber"

    def test_message_fan_archetype_defaults_to_none(self):
        """fan_archetype should default to None when not provided."""
        msg = Message(
            timestamp=datetime.now(),
            sender="creator",
            content="Hello there!",
            message_length=12,
        )

        assert msg.fan_archetype is None