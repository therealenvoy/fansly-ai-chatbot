"""
Tests for EmotionalArcTracker (TDD approach).

This module tracks emotional state across an entire conversation (session-level).
"""
import pytest
from datetime import datetime

from src.emotion.arc_tracker import EmotionalArcTracker
from src.emotion.models import EmotionAnalysis, EmotionalArc
from src.emotion.config import SentimentLabel, EmotionLabel, TrendLabel


class TestEmotionalArcTracker:
    """Test suite for EmotionalArcTracker"""
    
    def test_arc_tracker_initialization(self):
        """Test that arc tracker initializes with empty state"""
        tracker = EmotionalArcTracker(
            subscriber_id="sub_123",
            conversation_id="conv_456"
        )
        
        arc = tracker.get_arc()
        
        # Check basic identifiers
        assert arc.subscriber_id == "sub_123"
        assert arc.conversation_id == "conv_456"
        
        # Check empty state
        assert len(arc.messages) == 0
        assert arc.average_sentiment == 0.0
        assert arc.sentiment_trend == TrendLabel.NEUTRAL
        assert arc.dominant_emotion == EmotionLabel.NEUTRAL
        assert arc.is_engaged is False
        assert arc.is_cooling_off is False
        assert len(arc.warning_signals) == 0
        assert arc.purchase_readiness_index == 0.0
        assert arc.first_message_at is None
        assert arc.last_message_at is None
    
    def test_arc_tracker_update(self):
        """Test that update adds analysis and updates trend"""
        tracker = EmotionalArcTracker(
            subscriber_id="sub_123",
            conversation_id="conv_456"
        )
        
        # Update with a positive message
        analysis = tracker.update("I love this product!")
        
        # Check that analysis was returned
        assert isinstance(analysis, EmotionAnalysis)
        assert analysis.message == "I love this product!"
        
        # Check that arc was updated
        arc = tracker.get_arc()
        assert len(arc.messages) == 1
        assert arc.messages[0] == analysis
        assert arc.first_message_at is not None
        assert arc.last_message_at is not None
        
        # Should have positive sentiment
        assert analysis.vader_compound > 0
    
    def test_arc_tracker_warming_trend(self):
        """Test detection of improving sentiment (warming trend)"""
        tracker = EmotionalArcTracker(
            subscriber_id="sub_123",
            conversation_id="conv_456"
        )
        
        # Start negative, move to positive
        tracker.update("I'm not sure about this.")  # neutral/slightly negative
        tracker.update("Actually, this looks interesting.")  # slightly positive
        tracker.update("I really love this!")  # very positive
        
        arc = tracker.get_arc()
        
        # Should detect warming trend
        assert arc.sentiment_trend == TrendLabel.WARMING
        assert len(arc.messages) == 3
        
        # Average sentiment should be positive
        assert arc.average_sentiment > 0
    
    def test_arc_tracker_cooling_trend(self):
        """Test detection of declining sentiment (cooling trend)"""
        tracker = EmotionalArcTracker(
            subscriber_id="sub_123",
            conversation_id="conv_456"
        )
        
        # Start positive, move to negative
        tracker.update("This looks amazing!")  # very positive
        tracker.update("Hmm, not sure about the price.")  # neutral/slightly negative
        tracker.update("I don't like this at all.")  # negative
        
        arc = tracker.get_arc()
        
        # Should detect cooling trend
        assert arc.sentiment_trend == TrendLabel.COOLING
        assert arc.is_cooling_off is True
        assert len(arc.messages) == 3
        
        # Should have warning signals
        assert len(arc.warning_signals) > 0
    
    def test_arc_tracker_neutral_trend(self):
        """Test stable sentiment (neutral trend)"""
        tracker = EmotionalArcTracker(
            subscriber_id="sub_123",
            conversation_id="conv_456"
        )
        
        # Keep sentiment relatively stable and neutral
        tracker.update("Okay.")
        tracker.update("Sure.")
        tracker.update("Fine.")
        
        arc = tracker.get_arc()
        
        # Should remain neutral trend (no significant shift)
        assert arc.sentiment_trend == TrendLabel.NEUTRAL
        assert arc.is_cooling_off is False
        assert len(arc.messages) == 3
    
    def test_arc_tracker_purchase_ready(self):
        """Test detection of purchase readiness (high intent)"""
        tracker = EmotionalArcTracker(
            subscriber_id="sub_123",
            conversation_id="conv_456"
        )
        
        # Start with high-intent messages (need strong purchase language)
        tracker.update("I want to purchase this subscription!")  # high intent
        tracker.update("How do I buy it right now?")  # very high intent
        
        arc = tracker.get_arc()
        
        # Should detect some purchase readiness (based on actual intent scores)
        # With intent scores around 5-6, readiness should be > 0.3
        assert arc.purchase_readiness_index > 0.3
        assert len(arc.messages) == 2
        
        # At least one message should have high intent
        intent_scores = [msg.purchase_intent_score for msg in arc.messages]
        assert max(intent_scores) >= 5  # Verify we got decent intent scores
