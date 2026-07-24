"""
Tests for purchase intent scoring.
"""
import pytest
from src.emotion.intent_scorer import IntentScorer


@pytest.fixture
def scorer():
    """Create intent scorer instance."""
    return IntentScorer()


def test_intent_scorer_high_intent(scorer):
    """High intent messages (buy signals) should score >= 7."""
    messages = [
        "I want to buy your custom content",
        "How much does a PPV cost?",
        "Can I purchase a video from you?",
        "I'd like to order something custom"
    ]
    
    for msg in messages:
        score = scorer.score(msg, sentiment_compound=0.5, emotion="joy")
        assert score >= 7, f"Expected high intent for '{msg}', got {score}"


def test_intent_scorer_low_intent(scorer):
    """Casual messages should score <= 4."""
    messages = [
        "Hey how are you",
        "Good morning",
        "Have a nice day",
        "Thanks"
    ]
    
    for msg in messages:
        score = scorer.score(msg, sentiment_compound=0.3, emotion="neutral")
        assert score <= 4, f"Expected low intent for '{msg}', got {score}"


def test_intent_scorer_question_boosts_score(scorer):
    """Questions should increase intent score."""
    # Question version should score higher than statement
    question = "What content do you have?"
    statement = "You have content"
    
    question_score = scorer.score(question, sentiment_compound=0.3, emotion="neutral")
    statement_score = scorer.score(statement, sentiment_compound=0.3, emotion="neutral")
    
    assert question_score > statement_score, \
        f"Question score ({question_score}) should be higher than statement ({statement_score})"


def test_intent_scorer_keywords(scorer):
    """Purchase keywords should boost score."""
    # Message with purchase keywords
    with_keywords = "I love your content, want to buy something custom"
    without_keywords = "I love your content"
    
    with_score = scorer.score(with_keywords, sentiment_compound=0.5, emotion="joy")
    without_score = scorer.score(without_keywords, sentiment_compound=0.5, emotion="joy")
    
    assert with_score > without_score, \
        f"Message with keywords ({with_score}) should score higher than without ({without_score})"
