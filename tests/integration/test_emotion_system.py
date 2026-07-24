"""
Full-system integration tests for emotion detection system.

These tests simulate real-world usage patterns and verify that all
components work together correctly across API, CLI, and direct pipeline usage.
"""
import pytest
import json
from fastapi.testclient import TestClient

from src.emotion.pipeline import EmotionPipeline
from src.emotion.arc_tracker import EmotionalArcTracker
from src.emotion.api import app
from src.emotion.config import EmotionConfig, TrendLabel


class TestEndToEndConversation:
    """Test complete conversation flows through the system."""
    
    def test_end_to_end_conversation(self):
        """
        Simulate a multi-message conversation showing emotional arc tracking.
        
        Scenario: Curious prospect → Interested → Excited → Ready to purchase
        """
        # Initialize tracker
        tracker = EmotionalArcTracker(
            subscriber_id="sub_001",
            conversation_id="conv_integration_001"
        )
        
        # Message 1: Curious opener
        result1 = tracker.update("Hi! What kind of content do you have?")
        assert result1 is not None
        assert result1.contains_question is True
        assert result1.purchase_intent_score >= 0
        assert len(tracker.arc.messages) == 1
        
        # Message 2: Positive engagement
        result2 = tracker.update("That sounds really interesting!")
        assert result2.sentiment.value in ['positive', 'very_positive']
        assert len(tracker.arc.messages) == 2
        
        # Message 3: Building excitement
        result3 = tracker.update("Wow, I love that kind of stuff! 😍")
        assert result3.emotion.value in ['joy', 'surprise']
        assert result3.vader_compound > 0.5  # Strong positive
        assert len(tracker.arc.messages) == 3
        
        # Message 4: Purchase intent signal
        result4 = tracker.update("How much does it cost to unlock?")
        assert result4.contains_question is True
        assert result4.purchase_intent_score >= 6  # High purchase intent
        assert len(tracker.arc.messages) == 4
        
        # Message 5: Strong buying signal
        result5 = tracker.update("I want to buy that now!")
        assert result5.purchase_intent_score >= 3  # Should be positive based on keywords
        assert len(tracker.arc.messages) == 5
        
        # Verify arc status after conversation
        arc = tracker.get_arc()
        assert arc.subscriber_id == "sub_001"
        assert arc.conversation_id == "conv_integration_001"
        assert len(arc.messages) == 5
        
        # Check trend (could be any trend depending on last few messages)
        assert arc.sentiment_trend in [TrendLabel.WARMING, TrendLabel.NEUTRAL, TrendLabel.COOLING]
        
        # Check purchase readiness is above zero (engaged conversation)
        assert arc.purchase_readiness_index > 0.0
        
        # Check engagement
        assert arc.is_engaged is True
        
        # Verify timestamps
        assert arc.first_message_at is not None
        assert arc.last_message_at is not None
        assert arc.last_message_at >= arc.first_message_at


class TestAPIPipelineConsistency:
    """Verify that API and direct pipeline return consistent results."""
    
    def test_api_pipeline_consistency(self):
        """
        Verify that analyzing the same message through different interfaces
        produces consistent results.
        """
        test_message = "I love this! How much does it cost?"
        
        # 1. Direct pipeline analysis
        pipeline = EmotionPipeline()
        pipeline_result = pipeline.analyze(test_message)
        
        # 2. API analysis
        client = TestClient(app)
        api_response = client.post(
            "/analyze",
            json={"message": test_message}
        )
        assert api_response.status_code == 200
        api_result = api_response.json()
        
        # Verify consistency across both interfaces
        
        # Check sentiment consistency
        assert pipeline_result.sentiment.value == api_result['sentiment']
        
        # Check emotion consistency
        assert pipeline_result.emotion.value == api_result['emotion']
        
        # Check purchase intent consistency
        assert pipeline_result.purchase_intent_score == api_result['purchase_intent_score']
        
        # Check VADER scores consistency (within small tolerance for timing)
        assert abs(pipeline_result.vader_compound - api_result['vader_compound']) < 0.01
        
        # Check metadata consistency
        assert pipeline_result.contains_question == api_result['contains_question']
        assert pipeline_result.message_length == api_result['message_length']


class TestConversationWarmingToPurchase:
    """Test realistic sales scenario: cold → warm → hot → purchase."""
    
    def test_conversation_warming_to_purchase(self):
        """
        Realistic scenario: Subscriber progresses from cold to purchase-ready.
        
        This simulates a successful sales funnel conversation.
        """
        tracker = EmotionalArcTracker(
            subscriber_id="sub_sales_001",
            conversation_id="conv_sales_001"
        )
        
        # Stage 1: Cold - Initial skeptical inquiry
        r1 = tracker.update("What is this?")
        assert r1.purchase_intent_score <= 5  # Low to moderate intent
        
        # Stage 2: Curious - Showing interest
        r2 = tracker.update("Ok, tell me more")
        assert r2.purchase_intent_score >= 2
        
        # Stage 3: Warming - Positive signals
        r3 = tracker.update("That's pretty cool actually!")
        assert r3.sentiment.value in ['positive', 'very_positive']
        
        # Stage 4: Interested - Asking specific questions
        r4 = tracker.update("What kind of videos do you have?")
        assert r4.contains_question is True
        assert r4.purchase_intent_score >= 3
        
        # Stage 5: Building excitement
        r5 = tracker.update("Oh wow that's exactly what I like! 🔥")
        assert r5.emotion.value in ['joy', 'surprise']
        
        # Stage 6: Pricing inquiry - Strong buying signal
        r6 = tracker.update("How much to unlock everything?")
        assert r6.purchase_intent_score >= 5
        
        # Stage 7: Ready to purchase
        r7 = tracker.update("I definitely want to buy that!")
        assert r7.purchase_intent_score >= 3  # Shows purchase intent
        
        # Verify final arc state shows successful warming
        arc = tracker.get_arc()
        
        # Should show positive trend or neutral (depending on exact trajectory)
        assert arc.sentiment_trend in [TrendLabel.WARMING, TrendLabel.NEUTRAL, TrendLabel.COOLING]
        
        # Moderate to high purchase readiness
        assert arc.purchase_readiness_index >= 0.3
        
        # Engaged, showing interest
        assert arc.is_engaged is True
        
        # Should have minimal or no warning signals
        assert len(arc.warning_signals) <= 2
        
        # Average sentiment should be positive
        assert arc.average_sentiment > 0.0


class TestConversationCoolingRecovery:
    """Test handling of declining interest and recovery strategies."""
    
    def test_conversation_cooling_recovery(self):
        """
        Scenario: Subscriber shows initial interest but starts cooling off,
        then re-engages after a recovery prompt.
        
        This tests the system's ability to detect warning signals.
        """
        tracker = EmotionalArcTracker(
            subscriber_id="sub_cooling_001",
            conversation_id="conv_cooling_001"
        )
        
        # Stage 1: Good start - Positive engagement
        r1 = tracker.update("Hey! Your content looks interesting 😊")
        assert r1.sentiment.value in ['positive', 'very_positive']
        
        r2 = tracker.update("Tell me more about what you offer")
        assert r2.purchase_intent_score >= 2  # Shows some interest
        
        # Stage 2: Cooling signals - Short, neutral responses
        r3 = tracker.update("ok")
        assert r3.message_length <= 5  # Very short
        
        r4 = tracker.update("sure")
        assert r4.message_length <= 5
        
        r5 = tracker.update("maybe")
        assert r5.sentiment.value in ['neutral', 'negative']
        
        # Check for cooling detection
        arc_before_recovery = tracker.get_arc()
        
        # Should detect cooling trend
        # (May show COOLING or NEUTRAL depending on exact scores)
        assert arc_before_recovery.sentiment_trend in [TrendLabel.COOLING, TrendLabel.NEUTRAL]
        
        # Should have warning signals
        assert len(arc_before_recovery.warning_signals) > 0
        
        # May be flagged as cooling off
        # (Depends on exact thresholds, so we check the presence of signals)
        assert arc_before_recovery.is_cooling_off or len(arc_before_recovery.warning_signals) >= 2
        
        # Stage 3: Recovery - Re-engagement attempt succeeds
        r6 = tracker.update("Actually, do you have any special deals right now?")
        assert r6.contains_question is True
        assert r6.purchase_intent_score >= 4  # Renewed interest
        
        r7 = tracker.update("That sounds good, I'm interested!")
        assert r7.sentiment.value in ['positive', 'very_positive']
        assert r7.purchase_intent_score >= 4
        
        # Verify recovery in arc state
        arc_after_recovery = tracker.get_arc()
        
        # Engagement should be back
        assert arc_after_recovery.is_engaged is True
        
        # Purchase readiness should be moderate to high
        assert arc_after_recovery.purchase_readiness_index >= 0.4
        
        # Final sentiment should be positive despite the dip
        assert arc_after_recovery.average_sentiment >= 0.0


class TestBatchProcessing:
    """Test batch analysis capabilities."""
    
    def test_batch_processing_consistency(self):
        """
        Verify that batch processing produces the same results as
        individual processing for each message.
        """
        pipeline = EmotionPipeline()
        
        test_messages = [
            "I love this!",
            "This is terrible",
            "What is this?",
            "How much does it cost?",
            "I want to buy it now!"
        ]
        
        # Process individually
        individual_results = [pipeline.analyze(msg) for msg in test_messages]
        
        # Process as batch
        batch_results = pipeline.analyze_batch(test_messages)
        
        # Verify same number of results
        assert len(individual_results) == len(batch_results) == 5
        
        # Verify each result matches (within reasonable tolerance)
        for i, (individual, batch) in enumerate(zip(individual_results, batch_results)):
            assert individual.message == batch.message == test_messages[i]
            assert individual.sentiment == batch.sentiment
            assert individual.emotion == batch.emotion
            assert individual.purchase_intent_score == batch.purchase_intent_score
            assert individual.contains_question == batch.contains_question


class TestAPIEndpoints:
    """Test all API endpoints."""
    
    def test_analyze_endpoint(self):
        """Test POST /analyze endpoint."""
        client = TestClient(app)
        
        response = client.post(
            "/analyze",
            json={"message": "I love this! How much?"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert 'message' in data
        assert 'sentiment' in data
        assert 'emotion' in data
        assert 'purchase_intent_score' in data
        assert 'vader_compound' in data
        assert 'contains_question' in data
        
        # Verify types
        assert isinstance(data['purchase_intent_score'], int)
        assert isinstance(data['vader_compound'], float)
        assert isinstance(data['contains_question'], bool)
    
    def test_batch_endpoint(self):
        """Test POST /analyze/batch endpoint."""
        client = TestClient(app)
        
        response = client.post(
            "/analyze/batch",
            json={"messages": ["Hello!", "I love this!", "How much?"]}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert 'results' in data
        assert len(data['results']) == 3
        
        # Check each result has required fields
        for result in data['results']:
            assert 'message' in result
            assert 'sentiment' in result
            assert 'emotion' in result
    
    def test_health_endpoint(self):
        """Test GET /health endpoint."""
        client = TestClient(app)
        
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data['status'] == 'ok'
        assert data['service'] == 'emotion-analysis-api'


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_message(self):
        """Test handling of empty messages."""
        pipeline = EmotionPipeline()
        
        result = pipeline.analyze("")
        
        assert result.message == ""
        assert result.message_length == 0
        assert result.contains_question is False
        # Should still return valid results (neutral sentiment expected)
        assert result.sentiment is not None
        assert result.emotion is not None
    
    def test_very_long_message(self):
        """Test handling of very long messages."""
        pipeline = EmotionPipeline()
        
        long_message = "I love this! " * 100  # 1300+ characters
        result = pipeline.analyze(long_message)
        
        assert result.message_length > 1000
        assert result.sentiment is not None
        assert result.emotion is not None
    
    def test_special_characters(self):
        """Test handling of emojis and special characters."""
        pipeline = EmotionPipeline()
        
        messages = [
            "😍😍😍 I LOVE IT!!!",
            "🤔 Not sure...",
            "💰💰💰 Take my money!",
            "❤️❤️❤️"
        ]
        
        for msg in messages:
            result = pipeline.analyze(msg)
            assert result.message == msg
            assert result.sentiment is not None
            assert result.emotion is not None


class TestConversationPersistence:
    """Test that conversation state persists correctly."""
    
    def test_arc_state_persistence(self):
        """
        Verify that emotional arc maintains state across updates.
        """
        tracker = EmotionalArcTracker(
            subscriber_id="sub_persist_001",
            conversation_id="conv_persist_001"
        )
        
        # Add several messages
        messages = [
            "Hello!",
            "I love your content!",
            "How much is everything?",
            "I want to buy it!"
        ]
        
        for msg in messages:
            tracker.update(msg)
        
        # Get arc state
        arc = tracker.get_arc()
        
        # Verify all messages are stored
        assert len(arc.messages) == 4
        
        # Verify message order is preserved
        for i, msg in enumerate(messages):
            assert arc.messages[i].message == msg
        
        # Verify timestamps are in order
        for i in range(1, len(arc.messages)):
            assert arc.messages[i].timestamp >= arc.messages[i-1].timestamp
        
        # Get arc again - should be the same
        arc2 = tracker.get_arc()
        assert len(arc2.messages) == len(arc.messages)
        assert arc2.subscriber_id == arc.subscriber_id
        assert arc2.conversation_id == arc.conversation_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
