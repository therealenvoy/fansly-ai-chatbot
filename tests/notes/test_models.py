"""
Tests for FanNote Pydantic model.

Strict TDD: RED → GREEN → REFACTOR cycle.
"""

import pytest
from datetime import datetime
from src.notes.models import FanNote


class TestFanNote:
    """FanNote model: fields, defaults, and spend_tier property."""

    def test_fan_note_required_fields(self):
        """Create note with only required fields, verify all fields and defaults."""
        note = FanNote(
            fan_id="fan_001",
            creator_id="creator_001",
        )

        assert note.fan_id == "fan_001"
        assert note.creator_id == "creator_001"
        assert note.display_name is None
        assert note.preferences == []
        assert note.occupation is None
        assert note.total_spent == 0.0
        assert note.purchase_count == 0
        assert note.last_purchase_at is None
        assert note.emotional_triggers == []
        assert note.hard_limits == []
        assert note.notes == ""
        assert note.first_contact_at is None
        assert note.relationship_stage == "new"

    def test_fan_note_spend_tier_whale(self):
        """total_spent >= 500 -> 'whale'."""
        note = FanNote(fan_id="f1", creator_id="c1", total_spent=600.0)
        assert note.spend_tier == "whale"

    def test_fan_note_spend_tier_average(self):
        """total_spent >= 50 and < 500 -> 'average'."""
        note = FanNote(fan_id="f1", creator_id="c1", total_spent=80.0)
        assert note.spend_tier == "average"

    def test_fan_note_spend_tier_time_waster(self):
        """total_spent < 50 -> 'time_waster'."""
        note = FanNote(fan_id="f1", creator_id="c1", total_spent=0.0)
        assert note.spend_tier == "time_waster"

    def test_fan_note_all_fields(self):
        """Create note with all optional fields populated."""
        now = datetime(2026, 7, 24, 12, 0, 0)
        note = FanNote(
            fan_id="fan_002",
            creator_id="creator_002",
            display_name="JohnDoe",
            preferences=["cosplay", "feet"],
            occupation="engineer",
            total_spent=1200.0,
            purchase_count=15,
            last_purchase_at=now,
            emotional_triggers=["praise", "exclusivity"],
            hard_limits=["degradation"],
            notes="Loves custom content",
            first_contact_at=datetime(2025, 1, 1),
            relationship_stage="loyal",
        )

        assert note.fan_id == "fan_002"
        assert note.display_name == "JohnDoe"
        assert note.preferences == ["cosplay", "feet"]
        assert note.occupation == "engineer"
        assert note.total_spent == 1200.0
        assert note.purchase_count == 15
        assert note.last_purchase_at == now
        assert note.emotional_triggers == ["praise", "exclusivity"]
        assert note.hard_limits == ["degradation"]
        assert note.notes == "Loves custom content"
        assert note.first_contact_at == datetime(2025, 1, 1)
        assert note.relationship_stage == "loyal"
        assert note.spend_tier == "whale"