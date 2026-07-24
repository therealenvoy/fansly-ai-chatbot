"""Tests for the Delay Manager."""

import pytest

from src.timing.delays import DelayManager


class TestDelayManagerDefaults:
    """Tests for default configuration."""

    def test_defaults(self):
        """Default delays should match expected stage values."""
        dm = DelayManager()
        assert dm.get_delay("rapport") == 0
        assert dm.get_delay("tease") == 60
        assert dm.get_delay("offer") == 90
        assert dm.get_delay("handle") == 120
        assert dm.get_delay("close") == 150


class TestGetDelay:
    """Tests for get_delay method."""

    def test_get_delay(self):
        """get_delay should return correct value for each stage."""
        dm = DelayManager()
        assert dm.get_delay("tease") == 60
        assert dm.get_delay("close") == 150

    def test_get_delay_custom(self):
        """get_delay should respect custom config."""
        dm = DelayManager(delays={"rapport": 5, "tease": 30})
        assert dm.get_delay("rapport") == 5
        assert dm.get_delay("tease") == 30


class TestWaitMessage:
    """Tests for wait_message method."""

    def test_wait_message_for_tease(self):
        """Tease (60s) should produce 'give me 1 minutes...'."""
        dm = DelayManager()
        msg = dm.wait_message("tease")
        assert "give me" in msg.lower()
        assert "1 minutes" in msg

    def test_wait_message_not_for_rapport(self):
        """Rapport (0s delay) should NOT produce a waiting message."""
        dm = DelayManager()
        msg = dm.wait_message("rapport")
        assert "give me" not in msg.lower()

    def test_wait_message_for_close(self):
        """Close (150s) should produce 'give me 2 minutes...'."""
        dm = DelayManager()
        msg = dm.wait_message("close")
        assert "give me" in msg.lower()
        assert "2 minutes" in msg


class TestValidateDelay:
    """Tests for validate_delay method."""

    def test_validate_acceptable(self):
        """Delays within 50% of target should validate as True."""
        dm = DelayManager()
        # tease target = 60s; 50% range = 30-90s
        assert dm.validate_delay(60.0, "tease") is True   # exact
        assert dm.validate_delay(45.0, "tease") is True   # 25% under
        assert dm.validate_delay(85.0, "tease") is True   # ~42% over
        assert dm.validate_delay(30.0, "tease") is True   # exactly 50% under (boundary)
        assert dm.validate_delay(90.0, "tease") is True   # exactly 50% over (boundary)

    def test_validate_too_short(self):
        """Delays more than 50% off target should validate as False."""
        dm = DelayManager()
        # tease target = 60s
        assert dm.validate_delay(10.0, "tease") is False   # 83% under
        assert dm.validate_delay(91.0, "tease") is False   # >50% over
        assert dm.validate_delay(200.0, "tease") is False  # way over

    def test_validate_rapport_zero_target(self):
        """Rapport with 0 target: any delay > 1s should fail, ≤1s should pass."""
        dm = DelayManager()
        assert dm.validate_delay(0.0, "rapport") is True
        assert dm.validate_delay(0.5, "rapport") is True
        assert dm.validate_delay(1.0, "rapport") is True
        assert dm.validate_delay(5.0, "rapport") is False
