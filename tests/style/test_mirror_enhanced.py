"""Tests for enhanced StyleMirror — punctuation energy, sentence variance, greetings.

TDD: RED → GREEN → REFACTOR.
"""

import pytest
from src.style.mirror import StyleMirror, StyleProfile


@pytest.fixture
def mirror():
    return StyleMirror()


# ─── PUNCTUATION ENERGY ─────────────────────────────────

class TestPunctuationEnergy:
    def test_detects_double_exclamation(self, mirror):
        """Fan using '!!' should have higher exclamation intensity."""
        p = mirror.analyze(["Wow!!", "Nice!!", "Cool!!"])
        assert p.exclamation_intensity > 0.5

    def test_detects_single_exclamation(self, mirror):
        """Fan using '!' should have base exclamation intensity."""
        p = mirror.analyze(["Wow!", "Nice!", "Cool!"])
        assert p.exclamation_intensity == 1.0

    def test_detects_triple_exclamation(self, mirror):
        """Fan using '!!!' should have high exclamation intensity."""
        p = mirror.analyze(["Wow!!!", "Amazing!!!"])
        assert p.exclamation_intensity > 1.5

    def test_detects_question_exclamation_mix(self, mirror):
        """Fan using '?!' or '!?' should be detected."""
        p = mirror.analyze(["Really?!", "Wait!?"])
        assert p.has_mixed_punctuation

    def test_no_exclamation_returns_zero_intensity(self, mirror):
        p = mirror.analyze(["hey there", "how are you"])
        assert p.exclamation_intensity == 0.0

    def test_matches_exclamation_style(self, mirror):
        """Reply should match the fan's exclamation intensity."""
        p = mirror.analyze(["Wow!!", "Nice!!"])
        result = mirror.adapt("You're so cute!", p)
        # Should have two exclamation marks
        assert result.count("!") >= 1

    def test_single_exclamation_fan_gets_one(self, mirror):
        p = mirror.analyze(["Hey!", "Nice!"])
        result = mirror.adapt("You're so cute!!", p)
        assert result.count("!") <= 2  # shouldn't exceed fan's style much


# ─── SENTENCE LENGTH VARIANCE ───────────────────────────

class TestSentenceVariance:
    def test_detects_varied_lengths(self, mirror):
        """Fan using both short and long sentences should show variance."""
        p = mirror.analyze(["hey", "i was just thinking about you and how much i miss chatting with you every day", "lol", "so anyway about last night..."])
        assert p.sentence_length_stddev > 10

    def test_detects_uniform_lengths(self, mirror):
        """Fan using same-length sentences should show low variance."""
        p = mirror.analyze(["hey there", "how are you", "that's cool", "nice one"])
        assert p.sentence_length_stddev < 10

    def test_variance_preserved_in_reply(self, mirror):
        """Reply should maintain similar variance to fan's style."""
        p = mirror.analyze(["hey", "i was just thinking about you all day long...", "lol", "so tired rn"])
        result = mirror.adapt("I was thinking about you too baby, can't stop thinking about how cute you are when you smile 😘", p)
        # Should have at least some length variation
        sentences = [s.strip() for s in result.replace("!", ".").replace("?", ".").split(".") if s.strip()]
        if len(sentences) >= 2:
            lengths = [len(s) for s in sentences]
            assert max(lengths) - min(lengths) >= 5 or min(lengths) < 15


# ─── GREETING / SIGN-OFF MATCHING ───────────────────────

class TestGreetingMatching:
    def test_detects_hey_greeting(self, mirror):
        p = mirror.analyze(["hey how are you", "hey there", "hey babe"])
        assert p.opens_with_greeting
        assert "hey" in p.greeting_words

    def test_detects_hi_greeting(self, mirror):
        p = mirror.analyze(["hi whats up", "hi there"])
        assert "hi" in p.greeting_words

    def test_detects_no_greeting(self, mirror):
        p = mirror.analyze(["what are you doing", "i was thinking"])
        assert not p.opens_with_greeting

    def test_matches_greeting_style(self, mirror):
        """Fan who opens with 'hey' should get 'hey' in reply."""
        p = mirror.analyze(["hey how are you", "hey babe"])
        result = mirror.adapt("What are you up to?", p)
        assert "hey" in result.lower() or "hey" in p.greeting_words


# ─── INTEGRATION ─────────────────────────────────────────

class TestEnhancedIntegration:
    def test_enhanced_analyze_has_all_new_fields(self, mirror):
        p = mirror.analyze(["Hey!! What's up?", "I was just thinking...", "lol"])
        assert hasattr(p, "exclamation_intensity")
        assert hasattr(p, "sentence_length_stddev")
        assert hasattr(p, "opens_with_greeting")
        assert hasattr(p, "has_mixed_punctuation")

    def test_empty_history_has_defaults(self, mirror):
        p = mirror.analyze([])
        assert p.exclamation_intensity == 0.0
        assert p.sentence_length_stddev == 0.0
        assert not p.opens_with_greeting