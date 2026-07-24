"""
Tests for unified emotion pipeline that combines VADER, BERT, and Intent scoring.
"""
import pytest
from datetime import datetime

from src.emotion.pipeline import EmotionPipeline
from src.emotion.models import EmotionAnalysis
from src.emotion.config import EmotionConfig, SentimentLabel, EmotionLabel


class TestEmotionPipeline:
    """Test suite for EmotionPipeline integration"""
    
    @pytest.fixture
    def pipeline(self):
        """Create pipeline instance for testing"""
        config = EmotionConfig()
        return EmotionPipeline(config)
    
    def test_pipeline_complete_analysis(self, pipeline):
        """
        Test that pipeline returns complete EmotionAnalysis with all fields populated.
        
        This is the integration test - ensures all components work together correctly.
        """
        message = "I love this content! How much for custom videos? 🔥"
        
        result = pipeline.analyze(message)
        
        # Verify result type
        assert isinstance(result, EmotionAnalysis)
        
        # Verify input fields
        assert result.message == message
        assert isinstance(result.timestamp, datetime)
        
        # Verify VADER scores are present and in valid ranges
        assert -1.0 <= result.vader_compound <= 1.0
        assert 0.0 <= result.vader_pos <= 1.0
        assert 0.0 <= result.vader_neg <= 1.0
        assert 0.0 <= result.vader_neu <= 1.0
        
        # Verify sentiment classification
        assert isinstance(result.sentiment, SentimentLabel)
        # Should be positive given "love" sentiment
        assert result.sentiment in [SentimentLabel.POSITIVE, SentimentLabel.VERY_POSITIVE]
        
        # Verify BERT emotion classification
        assert isinstance(result.emotion, EmotionLabel)
        assert 0.0 <= result.emotion_confidence <= 1.0
        # Should be joy given "love" emotion
        assert result.emotion == EmotionLabel.JOY
        
        # Verify purchase intent score
        assert isinstance(result.purchase_intent_score, int)
        assert 0 <= result.purchase_intent_score <= 10
        # Should be high given "how much", "custom", "videos"
        assert result.purchase_intent_score >= 6
        
        # Verify metadata
        assert result.contains_question is True  # has "?"
        assert result.message_length == len(message)
        assert result.processing_time_ms > 0
    
    def test_pipeline_performance(self, pipeline):
        """
        Test that pipeline completes analysis in reasonable time (<1000ms).
        
        Performance is critical for real-time chat responses.
        """
        message = "This is a test message with some emotional content."
        
        result = pipeline.analyze(message)
        
        # Should complete in under 1 second
        assert result.processing_time_ms < 1000, \
            f"Pipeline took {result.processing_time_ms}ms, expected <1000ms"
        
        # Verify analysis still completed correctly
        assert isinstance(result, EmotionAnalysis)
        assert result.message == message
    
    def test_pipeline_batch_analysis(self, pipeline):
        """
        Test that pipeline can handle multiple messages efficiently.
        
        Batch processing is used for analyzing conversation history.
        """
        messages = [
            "Hi there!",
            "I love your content!",
            "How much for custom videos?",
            "This sucks, never mind.",
            "Actually, I'm interested again."
        ]
        
        results = pipeline.analyze_batch(messages)
        
        # Verify correct number of results
        assert len(results) == len(messages)
        
        # Verify all results are EmotionAnalysis objects
        for result in results:
            assert isinstance(result, EmotionAnalysis)
        
        # Verify messages match input
        for i, result in enumerate(results):
            assert result.message == messages[i]
        
        # Verify sentiment progression makes sense
        # Message 0: neutral greeting
        assert results[0].sentiment == SentimentLabel.NEUTRAL
        
        # Message 1: very positive
        assert results[1].sentiment in [SentimentLabel.POSITIVE, SentimentLabel.VERY_POSITIVE]
        
        # Message 2: question about purchase (should have moderate-high intent)
        # Note: Intent depends on sentiment + keywords, so 5+ is reasonable
        assert results[2].purchase_intent_score >= 5
        assert results[2].contains_question is True
        
        # Message 3: negative sentiment
        assert results[3].sentiment in [SentimentLabel.NEGATIVE, SentimentLabel.VERY_NEGATIVE]
        
        # Message 4: positive again with "interested" keyword
        assert results[4].sentiment in [SentimentLabel.POSITIVE, SentimentLabel.NEUTRAL]
        assert results[4].purchase_intent_score >= 4  # "interested" gives moderate intent
