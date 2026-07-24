"""Configuration for emotion detection and sentiment analysis."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class EmotionConfig:
    """Configuration for emotion detection models and thresholds."""
    
    # Model identifiers
    bert_model: str = "bhadresh-savani/distilbert-base-uncased-emotion"
    vader_lexicon: str = "vader_lexicon"
    
    # Sentiment thresholds (VADER compound score)
    very_negative_threshold: float = -0.6
    negative_threshold: float = -0.2
    neutral_threshold: float = 0.2
    positive_threshold: float = 0.6
    # very_positive is > positive_threshold
    
    # Emotion confidence threshold
    emotion_confidence_threshold: float = 0.3
    
    # Purchase intent keywords and weights
    purchase_keywords: Dict[str, float] = None
    
    # Emotional arc analysis windows
    short_window_size: int = 5  # messages
    medium_window_size: int = 15  # messages
    long_window_size: int = 50  # messages
    
    # Engagement signal weights
    sentiment_weight: float = 0.4
    emotion_weight: float = 0.3
    purchase_intent_weight: float = 0.3
    
    def __post_init__(self):
        """Initialize purchase keywords if not provided."""
        if self.purchase_keywords is None:
            self.purchase_keywords = {
                "buy": 1.0,
                "purchase": 1.0,
                "want": 0.7,
                "need": 0.6,
                "get": 0.5,
                "price": 0.8,
                "cost": 0.8,
                "pay": 0.9,
                "subscribe": 1.0,
                "subscription": 1.0,
            }


class SentimentLabel:
    """Sentiment classification labels."""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class EmotionLabel:
    """Emotion classification labels (from BERT model)."""
    ANGER = "anger"
    DISGUST = "disgust"
    FEAR = "fear"
    JOY = "joy"
    NEUTRAL = "neutral"
    SADNESS = "sadness"
    SURPRISE = "surprise"
