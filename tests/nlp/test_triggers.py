"""
Tests for NLPTriggerEngine — NLP trigger generation and anchoring.

Strict TDD: RED → GREEN → REFACTOR cycle.
"""

import pytest
from src.nlp.triggers import NLPTriggerEngine


class TestGenerateThoughtOfYou:
    """generate_thought_of_you — craft a message referencing fan interests/hobbies."""

    def test_thought_of_you_with_hobby(self):
        """If fan_notes has interests or hobbies, returns a crafted message."""
        engine = NLPTriggerEngine()
        fan_notes = {
            "interests": ["cosplay", "gaming"],
            "hobbies": ["photography"],
        }
        result = engine.generate_thought_of_you(fan_notes)

        assert result is not None
        assert isinstance(result, str)
        # Should reference at least one interest or hobby
        assert any(
            keyword in result.lower()
            for keyword in ["cosplay", "gaming", "photography"]
        )

    def test_thought_of_you_no_hobby_returns_none(self):
        """If fan_notes has no interests or hobbies, returns None."""
        engine = NLPTriggerEngine()
        fan_notes = {"display_name": "Alice", "occupation": "developer"}
        result = engine.generate_thought_of_you(fan_notes)

        assert result is None


class TestEmbedCommand:
    """embed_command — insert a command token into a message naturally."""

    def test_embed_command_inserts_naturally(self):
        """Command is embedded into the base message without breaking readability."""
        engine = NLPTriggerEngine()
        base = "Hey, just wanted to check in and see how you're doing today!"
        command = "/ppv_offer"
        result = engine.embed_command(base, command)

        assert command in result
        assert len(result) > len(base)
        # The original base message should still be mostly present
        assert "check in" in result


class TestAnchoring:
    """anchor_positive and get_anchors — record and retrieve anchor events."""

    def test_anchor_records_event(self):
        """anchor_positive stores an event for a fan_id."""
        engine = NLPTriggerEngine()
        engine.anchor_positive("fan_42", "orgasm_mentioned")

        anchors = engine.get_anchors("fan_42")
        assert "orgasm_mentioned" in anchors

    def test_get_anchors_returns_list(self):
        """get_anchors returns a list (possibly empty) for any fan_id."""
        engine = NLPTriggerEngine()

        # Unknown fan returns empty list
        result = engine.get_anchors("unknown_fan")
        assert isinstance(result, list)
        assert result == []

        # After anchoring, list includes the event
        engine.anchor_positive("fan_1", "event_a")
        engine.anchor_positive("fan_1", "event_b")
        result = engine.get_anchors("fan_1")
        assert result == ["event_a", "event_b"]


class TestDetectTriggerOpportunity:
    """detect_trigger_opportunity — determine which NLP techniques apply."""

    def test_detect_trigger_opportunity(self):
        """Returns list of applicable NLP technique names."""
        engine = NLPTriggerEngine()

        # Fan with interests should trigger thought_of_you
        fan_notes = {"interests": ["fitness"], "hobbies": ["cooking"]}
        opportunities = engine.detect_trigger_opportunity(
            "Hey, how are you?", fan_notes
        )
        assert isinstance(opportunities, list)
        assert "thought_of_you" in opportunities

        # Fan without interests should not trigger thought_of_you
        fan_notes_empty = {"display_name": "Bob"}
        opportunities_empty = engine.detect_trigger_opportunity(
            "Hi there!", fan_notes_empty
        )
        assert "thought_of_you" not in opportunities_empty
