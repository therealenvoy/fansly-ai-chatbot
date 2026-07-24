"""
Emotional Arc Tracker for tracking sentiment across conversations.

This module provides session-level emotional tracking, monitoring trends and
purchase readiness signals across multiple messages in a conversation.
"""
from typing import Optional, List
from datetime import datetime
from collections import Counter

from .pipeline import EmotionPipeline
from .models import EmotionAnalysis, EmotionalArc
from .config import EmotionConfig, TrendLabel, EmotionLabel


class EmotionalArcTracker:
    """
    Tracks emotional state across an entire conversation (session-level).
    
    This class maintains a conversation's emotional history and detects:
    - Sentiment trends (warming, cooling, neutral)
    - Purchase readiness signals
    - Warning signals (disengagement, negative sentiment)
    - Overall engagement levels
    
    Attributes:
        subscriber_id: Unique subscriber identifier
        conversation_id: Unique conversation identifier
        config: Emotion configuration
        pipeline: EmotionPipeline for analyzing messages
        arc: Current EmotionalArc state
    """
    
    def __init__(
        self,
        subscriber_id: str,
        conversation_id: str,
        config: Optional[EmotionConfig] = None
    ):
        """
        Initialize the emotional arc tracker.
        
        Args:
            subscriber_id: Unique subscriber identifier
            conversation_id: Unique conversation identifier
            config: EmotionConfig instance (creates default if None)
        """
        self.subscriber_id = subscriber_id
        self.conversation_id = conversation_id
        self.config = config or EmotionConfig()
        self.pipeline = EmotionPipeline(self.config)
        
        # Initialize empty arc state
        self.arc = EmotionalArc(
            subscriber_id=subscriber_id,
            conversation_id=conversation_id,
            messages=[],
            average_sentiment=0.0,
            sentiment_trend=TrendLabel.NEUTRAL,
            dominant_emotion=EmotionLabel.NEUTRAL,
            is_engaged=False,
            is_cooling_off=False,
            warning_signals=[],
            purchase_readiness_index=0.0,
            first_message_at=None,
            last_message_at=None
        )
    
    def update(self, message: str) -> EmotionAnalysis:
        """
        Analyze a new message and update the emotional arc.
        
        This method:
        1. Analyzes the message with the emotion pipeline
        2. Appends the analysis to the conversation history
        3. Recalculates current sentiment (moving average of last 3)
        4. Detects trends (warming/cooling/neutral)
        5. Detects purchase readiness
        6. Updates warning signals
        7. Updates the EmotionalArc model
        
        Args:
            message: User message text to analyze
            
        Returns:
            EmotionAnalysis object for this message
        """
        # Analyze message
        analysis = self.pipeline.analyze(message)
        
        # Append to history
        self.arc.messages.append(analysis)
        
        # Update timestamps
        if self.arc.first_message_at is None:
            self.arc.first_message_at = analysis.timestamp
        self.arc.last_message_at = analysis.timestamp
        
        # Recalculate arc metrics
        self._update_average_sentiment()
        self._detect_trend()
        self._update_dominant_emotion()
        self._detect_engagement()
        self._detect_purchase_readiness()
        self._update_warning_signals()
        
        return analysis
    
    def get_arc(self) -> EmotionalArc:
        """
        Get the current emotional arc state.
        
        Returns:
            EmotionalArc object with current conversation state
        """
        return self.arc
    
    def reset(self):
        """
        Reset the emotional arc to empty state.
        
        Clears all message history and resets metrics to defaults.
        Useful for starting a new conversation with the same IDs.
        """
        self.arc = EmotionalArc(
            subscriber_id=self.subscriber_id,
            conversation_id=self.conversation_id,
            messages=[],
            average_sentiment=0.0,
            sentiment_trend=TrendLabel.NEUTRAL,
            dominant_emotion=EmotionLabel.NEUTRAL,
            is_engaged=False,
            is_cooling_off=False,
            warning_signals=[],
            purchase_readiness_index=0.0,
            first_message_at=None,
            last_message_at=None
        )
    
    # Private helper methods
    
    def _update_average_sentiment(self):
        """Calculate moving average sentiment from last 3 messages."""
        if not self.arc.messages:
            self.arc.average_sentiment = 0.0
            return
        
        # Use last 3 messages for moving average
        recent_messages = self.arc.messages[-3:]
        sentiments = [msg.vader_compound for msg in recent_messages]
        self.arc.average_sentiment = sum(sentiments) / len(sentiments)
    
    def _detect_trend(self):
        """
        Detect sentiment trend (warming/cooling/neutral).
        
        Warming: sentiment improving over last 3 messages (> warming_threshold)
        Cooling: sentiment declining (< cooling_threshold)
        Neutral: stable sentiment
        """
        if len(self.arc.messages) < 3:
            # Not enough data for trend detection
            self.arc.sentiment_trend = TrendLabel.NEUTRAL
            self.arc.is_cooling_off = False
            return
        
        # Get last 3 messages
        recent = self.arc.messages[-3:]
        sentiments = [msg.vader_compound for msg in recent]
        
        # Calculate sentiment change (last - first of recent 3)
        sentiment_change = sentiments[-1] - sentiments[0]
        
        # Detect trend based on thresholds
        if sentiment_change > self.config.warming_threshold:
            self.arc.sentiment_trend = TrendLabel.WARMING
            self.arc.is_cooling_off = False
        elif sentiment_change < self.config.cooling_threshold:
            self.arc.sentiment_trend = TrendLabel.COOLING
            self.arc.is_cooling_off = True
        else:
            self.arc.sentiment_trend = TrendLabel.NEUTRAL
            self.arc.is_cooling_off = False
    
    def _update_dominant_emotion(self):
        """Calculate the most common emotion across all messages."""
        if not self.arc.messages:
            self.arc.dominant_emotion = EmotionLabel.NEUTRAL
            return
        
        # Count emotions
        emotions = [msg.emotion for msg in self.arc.messages]
        emotion_counts = Counter(emotions)
        
        # Get most common
        most_common = emotion_counts.most_common(1)[0][0]
        self.arc.dominant_emotion = most_common
    
    def _detect_engagement(self):
        """
        Detect if user is engaged based on recent activity.
        
        Engaged if:
        - Average sentiment is positive (> 0.1)
        - OR recent messages show warming trend
        - OR purchase intent is high
        """
        if not self.arc.messages:
            self.arc.is_engaged = False
            return
        
        # Check conditions
        positive_sentiment = self.arc.average_sentiment > 0.1
        warming_trend = self.arc.sentiment_trend == TrendLabel.WARMING
        
        # Check recent purchase intent
        recent_messages = self.arc.messages[-3:]
        high_intent = any(msg.purchase_intent_score >= 7 for msg in recent_messages)
        
        self.arc.is_engaged = positive_sentiment or warming_trend or high_intent
    
    def _detect_purchase_readiness(self):
        """
        Calculate purchase readiness index.
        
        Purchase ready when:
        - Intent score >= 7 for 2+ consecutive messages
        - High positive sentiment
        - Questions about purchase/price
        
        Returns index from 0.0 to 1.0
        """
        if len(self.arc.messages) < 2:
            self.arc.purchase_readiness_index = 0.0
            return
        
        # Check last 2 messages for consecutive high intent
        last_two = self.arc.messages[-2:]
        consecutive_high_intent = all(msg.purchase_intent_score >= 7 for msg in last_two)
        
        if consecutive_high_intent:
            # Strong purchase signal - high readiness
            self.arc.purchase_readiness_index = 0.8
        else:
            # Calculate based on average intent and sentiment
            recent_messages = self.arc.messages[-3:]
            avg_intent = sum(msg.purchase_intent_score for msg in recent_messages) / len(recent_messages)
            
            # Normalize intent (0-10) to readiness (0.0-1.0)
            intent_component = avg_intent / 10.0
            
            # Sentiment component (positive sentiment boosts readiness)
            sentiment_component = max(0.0, self.arc.average_sentiment)
            
            # Weighted average (intent 70%, sentiment 30%)
            self.arc.purchase_readiness_index = (
                0.7 * intent_component + 0.3 * sentiment_component
            )
            
            # Cap at 1.0
            self.arc.purchase_readiness_index = min(1.0, self.arc.purchase_readiness_index)
    
    def _update_warning_signals(self):
        """
        Update warning signals based on conversation state.
        
        Warning signals include:
        - negative_sentiment: Average sentiment is negative
        - cooling_off: Sentiment trend is cooling
        - short_responses: Recent messages are very short
        - low_engagement: User shows low engagement
        """
        signals = []
        
        # Check negative sentiment
        if self.arc.average_sentiment < -0.1:
            signals.append("negative_sentiment")
        
        # Check cooling trend
        if self.arc.is_cooling_off:
            signals.append("cooling_off")
        
        # Check for short responses (< 10 chars on average in last 3)
        if len(self.arc.messages) >= 3:
            recent = self.arc.messages[-3:]
            avg_length = sum(msg.message_length for msg in recent) / len(recent)
            if avg_length < 10:
                signals.append("short_responses")
        
        # Check engagement
        if not self.arc.is_engaged and len(self.arc.messages) >= 3:
            signals.append("low_engagement")
        
        self.arc.warning_signals = signals
