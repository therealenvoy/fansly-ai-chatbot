"""Data models for emotion detection and analysis."""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class EmotionAnalysis(BaseModel):
    """Result of emotion detection analysis for a single message."""
    
    message: str = Field(..., description="Original message text")
    timestamp: datetime = Field(..., description="When message was sent")
    
    # VADER sentiment scores
    vader_positive: float = Field(..., ge=0.0, le=1.0, description="VADER positive score")
    vader_neutral: float = Field(..., ge=0.0, le=1.0, description="VADER neutral score")
    vader_negative: float = Field(..., ge=0.0, le=1.0, description="VADER negative score")
    vader_compound: float = Field(..., ge=-1.0, le=1.0, description="VADER compound score")
    
    # Sentiment classification
    sentiment: str = Field(..., description="Sentiment label (very_negative to very_positive)")
    
    # BERT emotion detection
    emotion: str = Field(..., description="Primary emotion detected")
    emotion_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in emotion prediction")
    emotion_scores: Dict[str, float] = Field(..., description="All emotion scores from BERT")
    
    # Purchase intent
    purchase_intent_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Likelihood of purchase intent"
    )
    purchase_keywords_found: List[str] = Field(
        default_factory=list,
        description="Purchase-related keywords detected"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "I love this! Want to buy more",
                "timestamp": "2024-07-24T14:30:00Z",
                "vader_positive": 0.8,
                "vader_neutral": 0.2,
                "vader_negative": 0.0,
                "vader_compound": 0.8,
                "sentiment": "very_positive",
                "emotion": "joy",
                "emotion_confidence": 0.92,
                "emotion_scores": {"joy": 0.92, "surprise": 0.05, "neutral": 0.03},
                "purchase_intent_score": 0.85,
                "purchase_keywords_found": ["love", "want", "buy"]
            }
        }


class EmotionalArc(BaseModel):
    """Emotional trajectory analysis for a subscriber."""
    
    subscriber_id: str = Field(..., description="Unique subscriber identifier")
    messages: List[EmotionAnalysis] = Field(..., description="Analyzed messages in chronological order")
    
    # Arc metrics
    average_sentiment: float = Field(..., ge=-1.0, le=1.0, description="Average VADER compound score")
    sentiment_trend: float = Field(..., description="Linear trend of sentiment over time (slope)")
    sentiment_volatility: float = Field(..., ge=0.0, description="Standard deviation of sentiment")
    
    dominant_emotion: str = Field(..., description="Most frequent emotion in arc")
    emotion_distribution: Dict[str, float] = Field(..., description="Distribution of emotions")
    
    # Engagement signals
    average_purchase_intent: float = Field(..., ge=0.0, le=1.0, description="Average purchase intent")
    engagement_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall engagement score (weighted combination)"
    )
    
    # Temporal metadata
    first_message_time: datetime = Field(..., description="Timestamp of first message")
    last_message_time: datetime = Field(..., description="Timestamp of last message")
    message_count: int = Field(..., ge=1, description="Total number of messages analyzed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "subscriber_id": "sub_12345",
                "messages": [],
                "average_sentiment": 0.65,
                "sentiment_trend": 0.02,
                "sentiment_volatility": 0.15,
                "dominant_emotion": "joy",
                "emotion_distribution": {"joy": 0.6, "surprise": 0.2, "neutral": 0.2},
                "average_purchase_intent": 0.45,
                "engagement_score": 0.72,
                "first_message_time": "2024-07-20T10:00:00Z",
                "last_message_time": "2024-07-24T14:30:00Z",
                "message_count": 25
            }
        }
