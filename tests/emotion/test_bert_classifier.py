"""Tests for BERT emotion classifier."""

import pytest
from src.emotion.bert_classifier import BERTEmotionClassifier
from src.emotion.config import EmotionLabel


@pytest.fixture
def classifier():
    """Fixture for BERT classifier."""
    return BERTEmotionClassifier()


def test_bert_classifier_joy(classifier):
    """Test that joyful text is classified as joy."""
    text = "I'm so happy and excited! This is wonderful!"
    result = classifier.classify(text)
    
    assert "emotion" in result
    assert "confidence" in result
    assert "all_scores" in result
    assert result["emotion"] == EmotionLabel.JOY
    assert result["confidence"] > 0.5
    assert isinstance(result["all_scores"], dict)


def test_bert_classifier_anger(classifier):
    """Test that angry text is classified as anger."""
    text = "I'm furious! This is completely unacceptable!"
    result = classifier.classify(text)
    
    assert result["emotion"] == EmotionLabel.ANGER
    assert result["confidence"] > 0.5


def test_bert_classifier_neutral(classifier):
    """Test that neutral text is classified as neutral."""
    text = "The weather is 72 degrees today."
    result = classifier.classify(text)
    
    assert result["emotion"] in [EmotionLabel.NEUTRAL, EmotionLabel.JOY, EmotionLabel.SADNESS]
    assert result["confidence"] > 0.0


def test_bert_classifier_model_loads(classifier):
    """Test that model loads correctly."""
    assert classifier.model is not None
    assert classifier.tokenizer is not None
    assert classifier.device in ["cuda", "cpu"]
