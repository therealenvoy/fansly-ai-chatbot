"""Tests for PersonaLoader — loads YAML persona configs."""

import pytest
from src.persona.loader import PersonaLoader
from src.persona.models import PersonaDocument


class TestPersonaLoader:
    """PersonaLoader — reads {creator_id}.yaml from config/creators/."""

    def test_load_persona_from_yaml(self):
        """Loader loads sunny_charm, verify fields populated correctly."""
        loader = PersonaLoader()
        doc = loader.load("sunny_charm")

        assert isinstance(doc, PersonaDocument)
        assert doc.creator_id == "sunny_charm"
        assert doc.tone == "flirty"
        assert "hey babe" in doc.signature_phrases
        assert "daddy" in doc.forbidden_phrases
        assert doc.common_typos == {"your": "ur", "you": "u", "are": "r"}
        assert doc.emoji_style == "moderate"
        assert doc.sentence_style == "short_punchy"
        assert "babe" in doc.pet_names
        assert "No meetups" in doc.content_boundaries
        assert doc.voice_note_frequency == "occasional"
        assert doc.response_length_target == 40

    def test_load_nonexistent_creator_raises(self):
        """FileNotFoundError for missing config."""
        loader = PersonaLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent_creator_xyz")