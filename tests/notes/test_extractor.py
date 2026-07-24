"""
Tests for NoteExtractor — LLM-based extraction and merge logic.

Strict TDD: RED → GREEN → REFACTOR cycle.
"""

import pytest
from src.notes.models import FanNote
from src.notes.extractor import NoteExtractor


def make_mock_llm(return_value: dict):
    """Create a mock LLM callable that returns a predefined dict."""
    async def mock_llm(message: str) -> dict:
        return return_value

    return mock_llm


class TestNoteExtractor:
    """NoteExtractor: extract and merge methods."""

    @pytest.mark.asyncio
    async def test_extract_returns_dict(self):
        """extract should return a dict with extracted fields."""
        mock = make_mock_llm({
            "preferences": ["cosplay"],
            "occupation": "developer",
            "emotional_triggers": ["praise"],
        })
        extractor = NoteExtractor(llm_client=mock)
        result = await extractor.extract("I love cosplay content!")

        assert isinstance(result, dict)
        assert result["preferences"] == ["cosplay"]
        assert result["occupation"] == "developer"
        assert result["emotional_triggers"] == ["praise"]

    def test_extractor_merge_adds_preferences(self):
        """Merge new preferences into existing note."""
        note = FanNote(fan_id="f1", creator_id="c1", preferences=["cosplay"])
        extracted = {"preferences": ["feet"]}

        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, extracted)

        assert "cosplay" in merged.preferences
        assert "feet" in merged.preferences
        assert merged.fan_id == "f1"  # unchanged
        assert merged.creator_id == "c1"  # unchanged

    def test_extractor_merge_preserves_existing_name(self):
        """Don't overwrite display_name if already set."""
        note = FanNote(
            fan_id="f1",
            creator_id="c1",
            display_name="Alice",
        )
        extracted = {"display_name": "Bob"}

        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, extracted)

        assert merged.display_name == "Alice"  # preserved

    def test_extractor_merge_sets_name_if_none(self):
        """Set display_name if it's currently None."""
        note = FanNote(fan_id="f1", creator_id="c1", display_name=None)
        extracted = {"display_name": "Charlie"}

        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, extracted)

        assert merged.display_name == "Charlie"

    def test_extractor_merge_handles_empty_extracted(self):
        """Merge should return note unchanged if extracted is empty."""
        note = FanNote(
            fan_id="f1",
            creator_id="c1",
            display_name="Diana",
            preferences=["lingerie"],
        )
        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, {})

        assert merged.display_name == "Diana"
        assert merged.preferences == ["lingerie"]

    def test_extractor_merge_appends_emotional_triggers(self):
        """New emotional triggers should be appended, not replace."""
        note = FanNote(
            fan_id="f1",
            creator_id="c1",
            emotional_triggers=["praise"],
        )
        extracted = {"emotional_triggers": ["exclusivity"]}

        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, extracted)

        assert "praise" in merged.emotional_triggers
        assert "exclusivity" in merged.emotional_triggers

    def test_extractor_merge_appends_hard_limits(self):
        """New hard_limits should be appended, not replace."""
        note = FanNote(
            fan_id="f1",
            creator_id="c1",
            hard_limits=["degradation"],
        )
        extracted = {"hard_limits": ["cuckolding"]}

        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, extracted)

        assert "degradation" in merged.hard_limits
        assert "cuckolding" in merged.hard_limits

    def test_extractor_merge_updates_occupation(self):
        """Occupation should be set if newer."""
        note = FanNote(fan_id="f1", creator_id="c1", occupation=None)
        extracted = {"occupation": "doctor"}

        extractor = NoteExtractor(llm_client=make_mock_llm({}))
        merged = extractor.merge(note, extracted)

        assert merged.occupation == "doctor"