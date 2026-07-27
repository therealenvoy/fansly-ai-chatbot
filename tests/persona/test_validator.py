"""Tests for PersonaValidator — checks messages for voice violations."""

import pytest
from src.persona.validator import PersonaValidator, ValidationResult
from src.persona.models import PersonaDocument


class TestValidationResult:
    """ValidationResult dataclass tests."""

    def test_validation_result_has_fields(self):
        """ValidationResult should have passed (bool) and violations (list[str])."""
        result = ValidationResult(passed=True, violations=[])
        assert result.passed is True
        assert result.violations == []

        result_fail = ValidationResult(passed=False, violations=["forbidden: daddy"])
        assert result_fail.passed is False
        assert result_fail.violations == ["forbidden: daddy"]


class TestPersonaValidator:
    """PersonaValidator — enforces voice consistency."""

    @pytest.fixture
    def persona_doc(self):
        """Create a sample PersonaDocument for validation tests."""
        return PersonaDocument(
            creator_id="test",
            tone="flirty",
            signature_phrases=["hey babe"],
            forbidden_phrases=["daddy", "bro", "what's up dude"],
            emoji_style="moderate",
            sentence_style="short_punchy",
        )

    def test_validator_flags_forbidden_phrase(self, persona_doc):
        """Validate message containing 'daddy' returns passed=False."""
        validator = PersonaValidator(persona_doc)
        result = validator.validate("hey daddy how are you")

        assert result.passed is False
        assert len(result.violations) >= 1
        assert any("daddy" in v.lower() for v in result.violations)

    def test_validator_passes_clean_message(self, persona_doc):
        """Validate clean message returns passed=True."""
        validator = PersonaValidator(persona_doc)
        result = validator.validate("Hey sweetie, missed you today!")

        assert result.passed is True
        assert result.violations == []

    def test_validator_case_insensitive_forbidden(self, persona_doc):
        """Forbidden phrase detection should be case-insensitive."""
        validator = PersonaValidator(persona_doc)
        result = validator.validate("Hey DADDY!")

        assert result.passed is False

    def test_validator_multiple_violations(self, persona_doc):
        """Message with multiple forbidden phrases reports all of them."""
        validator = PersonaValidator(persona_doc)
        result = validator.validate("what's up dude, bro!")

        assert result.passed is False
        assert len(result.violations) >= 2

    def test_short_forbidden_word_does_not_match_inside_normal_words(self):
        persona = PersonaDocument(
            creator_id="test",
            tone="flirty",
            signature_phrases=[],
            forbidden_phrases=["yo"],
            emoji_style="moderate",
            sentence_style="short_punchy",
        )
        validator = PersonaValidator(persona)

        assert validator.validate(
            "how was your day? hope you're doing well"
        ).passed is True
        violation = validator.validate("yo, how was your day?")
        assert violation.passed is False
        assert violation.violations == ["forbidden: yo"]

    def test_forbidden_phrase_allows_flexible_internal_whitespace(
        self,
        persona_doc,
    ):
        result = PersonaValidator(persona_doc).validate(
            "what's   up dude?"
        )

        assert result.passed is False
        assert "forbidden: what's up dude" in result.violations
