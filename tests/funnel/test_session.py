"""Tests for FanSession — RED phase (tests written before implementation)."""

from src.funnel.session import FanSession
from src.funnel.state_machine import FunnelStage


class TestFanSession:
    """All fan session tests."""

    def test_fan_session_tracks_messages(self):
        """Adding messages should increment message_count."""
        session = FanSession(fan_id="fan-1", creator_id="creator-1")
        assert session.message_count == 0

        session.add_message(sender="fan", content="Hey!")
        session.add_message(sender="creator", content="Hi there!")
        assert session.message_count == 2

    def test_fan_session_detects_ppv_block(self):
        """With only 1 rapport message, min_messages_before_tease > 0."""
        session = FanSession(fan_id="fan-1", creator_id="creator-1")
        assert session.funnel.current_stage == FunnelStage.RAPPORT

        # Add just one rapport message
        session.add_message(sender="fan", content="Hello")
        # Not enough rapport messages yet
        assert session.funnel.min_messages_before_tease() > 0
        assert session.funnel.min_messages_before_tease() == 1