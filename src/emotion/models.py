"""
Pydantic models for emotion detection
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List


class EmotionAnalysis(BaseModel):
    """Single message emotion analysis result"""
    
    # Input
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # VADER results
    vader_compound: float = Field(..., ge=-1.0, le=1.0)
    vader_pos: float = Field(..., ge=0.0, le=1.0)
    vader_neg: float = Field(..., ge=0.0, le=1.0)
    vader_neu: float = Field(..., ge=0.0, le=1.0)
    
    # Sentiment classification
    sentiment: str  # very_negative | negative | neutral | positive | very_positive
    
    # BERT emotion classification
    emotion: str  # anger | disgust | fear | joy | neutral | sadness | surprise
    emotion_confidence: float = Field(..., ge=0.0, le=1.0)
    
    # Purchase intent score (0-10)
    purchase_intent_score: int = Field(..., ge=0, le=10)
    
    # Metadata
    contains_question: bool = False
    message_length: int = 0
    processing_time_ms: float = 0.0


class EmotionalArc(BaseModel):
    """Emotional trajectory across conversation"""
    
    subscriber_id: str
    conversation_id: str
    
    # Message history
    messages: List[EmotionAnalysis] = []
    
    # Arc metrics
    average_sentiment: float = Field(default=0.0, ge=-1.0, le=1.0)
    sentiment_trend: str = "neutral"  # warming | cooling | neutral
    dominant_emotion: str = "neutral"
    
    # Engagement signals
    is_engaged: bool = False
    is_cooling_off: bool = False
    warning_signals: List[str] = []  # ["negative_sentiment", "short_responses", etc]
    
    # Purchase readiness
    purchase_readiness_index: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Timestamps
    first_message_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
