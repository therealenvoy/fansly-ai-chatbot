"""Emotion detection and sentiment analysis module."""

from .pipeline import EmotionPipeline
from .models import EmotionAnalysis, EmotionalArc
from .config import EmotionConfig, SentimentLabel, EmotionLabel, TrendLabel

__all__ = [
    'EmotionPipeline',
    'EmotionAnalysis',
    'EmotionalArc',
    'EmotionConfig',
    'SentimentLabel',
    'EmotionLabel',
    'TrendLabel',
]
