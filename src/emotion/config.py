"""Configuration for emotion detection and sentiment analysis."""

from pydantic import BaseModel


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


class SentimentLabel(str):
    """Sentiment labels"""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class EmotionLabel(str):
    """Emotion labels from BERT model"""
    ANGER = "anger"
    DISGUST = "disgust"
    FEAR = "fear"
    JOY = "joy"
    NEUTRAL = "neutral"
    SADNESS = "sadness"
    SURPRISE = "surprise"
