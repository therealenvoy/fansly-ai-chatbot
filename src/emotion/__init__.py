"""Emotion detection and sentiment analysis module."""

from .pipeline import EmotionPipeline
from .models import EmotionAnalysis, EmotionalArc
from .config import EmotionConfig, SentimentLabel, EmotionLabel, TrendLabel
from .arc_tracker import EmotionalArcTracker

__all__ = [
    'EmotionPipeline',
    'EmotionAnalysis',
    'EmotionalArc',
    'EmotionConfig',
    'SentimentLabel',
    'EmotionLabel',
    'TrendLabel',
    'EmotionalArcTracker',
]
