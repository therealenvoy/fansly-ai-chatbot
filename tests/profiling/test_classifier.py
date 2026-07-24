"""
Tests for fan personality classification from early messages.
"""
import pytest
from src.profiling.classifier import FanClassifier, ClassificationResult


@pytest.fixture
def classifier():
    """Create a fresh FanClassifier instance."""
    return FanClassifier()


class TestClassifyPersonalityTypes:
    """Tests for classifying fan personality types."""

    def test_classify_instant_buyer(self, classifier):
        """Messages containing 'content' and 'buy' → instant_buyer."""
        messages = [
            "Hey, I love your content",
            "How can I buy your videos?",
        ]
        result = classifier.classify(messages)
        assert result.personality_type == "instant_buyer"

    def test_classify_quiet_lurker(self, classifier):
        """Very short messages → quiet_lurker."""
        messages = ["hi", "ok", "cool"]
        result = classifier.classify(messages)
        assert result.personality_type == "quiet_lurker"

    def test_classify_chatty_fan(self, classifier):
        """Long, engaged messages → chatty_fan."""
        messages = [
            "Hey there! I've been following you for a while now and I just wanted "
            "to say that your content is absolutely amazing. I really love the way "
            "you engage with your fans and I'm super excited to finally reach out "
            "and say hello! How's your day going?",
            "Thank you so much for the warm welcome! I've been a fan for about "
            "six months now and honestly, your content just keeps getting better "
            "and better. I'd love to chat more and get to know you better if that's "
            "something you're open to!",
        ]
        result = classifier.classify(messages)
        assert result.personality_type == "chatty_fan"

    def test_classify_tester(self, classifier):
        """Messages asking 'why so much' → tester."""
        messages = [
            "Hey, I saw your prices",
            "why so much for a video?",
        ]
        result = classifier.classify(messages)
        assert result.personality_type == "tester"

    def test_classify_attention_seeker(self, classifier):
        """Messages with 'anyone there' → attention_seeker."""
        messages = [
            "hello?",
            "anyone there?",
        ]
        result = classifier.classify(messages)
        assert result.personality_type == "attention_seeker"


class TestClassificationResult:
    """Tests for ClassificationResult properties."""

    def test_classifier_returns_confidence(self, classifier):
        """result.confidence should be between 0 and 1."""
        messages = ["hi", "how are you", "I like your stuff"]
        result = classifier.classify(messages)
        assert 0.0 <= result.confidence <= 1.0

    def test_classifier_with_empty_messages(self, classifier):
        """Empty message list defaults to quiet_lurker with low confidence."""
        result = classifier.classify([])
        assert result.personality_type == "quiet_lurker"
        assert result.confidence < 0.5