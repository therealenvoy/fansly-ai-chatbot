"""Tests for PersonaDocument Pydantic model."""

import pytest
from src.persona.models import PersonaDocument


class TestPersonaDocument:
    """PersonaDocument model — enforces voice consistency config."""

    def test_persona_document_required_fields(self):
        """Create PersonaDocument with all required fields and verify."""
        doc = PersonaDocument(
            creator_id="sunny_charm",
            tone="flirty",
            signature_phrases=["hey babe", "missed you"],
            forbidden_phrases=["daddy", "bro"],
            common_typos={"your": "ur", "you": "u"},
            emoji_style="moderate",
            sentence_style="short_punchy",
            pet_names=["babe", "sweetie"],
            content_boundaries=["No meetups"],
            sample_winning_messages=["Hey babe, missed you today!"],
            voice_note_frequency="occasional",
            response_length_target=40,
        )

        assert doc.creator_id == "sunny_charm"
        assert doc.tone == "flirty"
        assert doc.signature_phrases == ["hey babe", "missed you"]
        assert doc.forbidden_phrases == ["daddy", "bro"]
        assert doc.common_typos == {"your": "ur", "you": "u"}
        assert doc.emoji_style == "moderate"
        assert doc.sentence_style == "short_punchy"
        assert doc.pet_names == ["babe", "sweetie"]
        assert doc.content_boundaries == ["No meetups"]
        assert doc.sample_winning_messages == ["Hey babe, missed you today!"]
        assert doc.voice_note_frequency == "occasional"
        assert doc.response_length_target == 40

    def test_persona_document_defaults(self):
        """Verify optional fields have correct defaults."""
        doc = PersonaDocument(
            creator_id="test",
            tone="neutral",
            signature_phrases=[],
            forbidden_phrases=[],
            emoji_style="minimal",
            sentence_style="casual",
        )

        assert doc.common_typos == {}
        assert doc.pet_names == []
        assert doc.content_boundaries == []
        assert doc.sample_winning_messages == []
        assert doc.voice_note_frequency == "occasional"
        assert doc.response_length_target == 40