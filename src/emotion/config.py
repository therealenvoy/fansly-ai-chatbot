"""Configuration for emotion detection and sentiment analysis."""

from enum import Enum
from pydantic import BaseModel, model_validator


class EmotionConfig(BaseModel):
    """Configuration for emotion detection pipeline"""
    
    # Model settings
    bert_model: str = "j-hartmann/emotion-english-distilroberta-base"
    vader_lexicon: str = "vader_lexicon"
    
    # Thresholds
    vader_pos_threshold: float = 0.05
    vader_neg_threshold: float = -0.05
    confidence_threshold: float = 0.6
    
    # Emotional arc settings
    warming_threshold: float = 0.1  # +0.1 sentiment shift = warming
    cooling_threshold: float = -0.1  # -0.1 sentiment shift = cooling
    
    # Purchase intent scoring weights
    intent_keyword_weight: float = 0.3
    intent_sentiment_weight: float = 0.4
    intent_question_weight: float = 0.3
    
    @model_validator(mode='after')
    def validate_intent_weights(self):
        """Ensure intent weights sum to 1.0"""
        total = self.intent_keyword_weight + self.intent_sentiment_weight + self.intent_question_weight
        if abs(total - 1.0) > 0.001:  # Allow small floating point errors
            raise ValueError(f"Intent weights must sum to 1.0, got {total}")
        return self


class SentimentLabel(str, Enum):
    """Sentiment labels"""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class EmotionLabel(str, Enum):
    """Emotion labels from BERT model"""
    ANGER = "anger"
    DISGUST = "disgust"
    FEAR = "fear"
    JOY = "joy"
    NEUTRAL = "neutral"
    SADNESS = "sadness"
    SURPRISE = "surprise"


class TrendLabel(str, Enum):
    """Sentiment trend labels"""
    WARMING = "warming"
    COOLING = "cooling"
    NEUTRAL = "neutral"
