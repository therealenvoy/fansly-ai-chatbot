"""Tests for VADER sentiment analyzer."""

import pytest
from src.emotion.vader_analyzer import VADERAnalyzer
from src.emotion.config import EmotionConfig, SentimentLabel


@pytest.fixture
def vader_analyzer():
    """Create VADERAnalyzer instance with default config."""
    config = EmotionConfig()
    return VADERAnalyzer(config)


def test_vader_analyzer_positive_sentiment(vader_analyzer):
    """Test VADER analyzer with clearly positive text."""
    text = "I absolutely love this! It's amazing and wonderful!"
    result = vader_analyzer.analyze(text)
    
    # Check structure
    assert "compound" in result
    assert "pos" in result
    assert "neg" in result
    assert "neu" in result
    assert "sentiment" in result
    
    # Check values
    assert result["compound"] > 0.5  # Strong positive
    assert result["pos"] > result["neg"]
    assert result["sentiment"] in [SentimentLabel.POSITIVE, SentimentLabel.VERY_POSITIVE]


def test_vader_analyzer_negative_sentiment(vader_analyzer):
    """Test VADER analyzer with clearly negative text."""
    text = "This is terrible and awful. I hate it so much!"
    result = vader_analyzer.analyze(text)
    
    # Check structure
    assert "compound" in result
    assert "pos" in result
    assert "neg" in result
    assert "neu" in result
    assert "sentiment" in result
    
    # Check values
    assert result["compound"] < -0.5  # Strong negative
    assert result["neg"] > result["pos"]
    assert result["sentiment"] in [SentimentLabel.NEGATIVE, SentimentLabel.VERY_NEGATIVE]


def test_vader_analyzer_neutral_sentiment(vader_analyzer):
    """Test VADER analyzer with neutral text."""
    text = "The package arrived on Tuesday."
    result = vader_analyzer.analyze(text)
    
    # Check structure
    assert "compound" in result
    assert "pos" in result
    assert "neg" in result
    assert "neu" in result
    assert "sentiment" in result
    
    # Check values
    assert -0.1 < result["compound"] < 0.1  # Near zero
    assert result["sentiment"] == SentimentLabel.NEUTRAL


def test_vader_analyzer_emoji_handling(vader_analyzer):
    """Test VADER analyzer correctly handles emojis."""
    text = "I love this 😍🔥💕"
    result = vader_analyzer.analyze(text)
    
    # Check structure
    assert "compound" in result
    assert "sentiment" in result
    
    # Emojis should contribute to positive sentiment
    assert result["compound"] > 0
    assert result["sentiment"] in [SentimentLabel.POSITIVE, SentimentLabel.VERY_POSITIVE]
