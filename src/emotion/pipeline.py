"""
Unified emotion analysis pipeline combining VADER, BERT, and Intent scoring.

This is the main integration point for the emotion detection system.
"""
import time
from typing import List
from datetime import datetime

from .config import EmotionConfig, EmotionLabel
from .models import EmotionAnalysis
from .vader_analyzer import VADERAnalyzer
from .bert_classifier import BERTEmotionClassifier
from .intent_scorer import IntentScorer


class EmotionPipeline:
    """
    Unified emotion analysis pipeline.
    
    Combines three analyzers:
    1. VADER: Fast sentiment analysis with social media support
    2. BERT: Accurate emotion classification using transformers
    3. Intent Scorer: Purchase intent detection
    
    Returns complete EmotionAnalysis objects with all fields populated.
    
    Attributes:
        config: Emotion configuration
        vader: VADER sentiment analyzer
        bert: BERT emotion classifier
        intent: Purchase intent scorer
    """
    
    def __init__(self, config: EmotionConfig = None):
        """
        Initialize the emotion pipeline with all analyzers.
        
        Args:
            config: EmotionConfig instance (creates default if None)
        """
        self.config = config or EmotionConfig()
        
        # Initialize all analyzers
        self.vader = VADERAnalyzer(self.config)
        self.bert = BERTEmotionClassifier(self.config)
        self.intent = IntentScorer()
    
    def analyze(self, message: str) -> EmotionAnalysis:
        """
        Perform complete emotion analysis on a single message.
        
        This is the main integration method that:
        1. Runs VADER for fast sentiment
        2. Runs BERT for accurate emotion
        3. Runs Intent scorer for purchase signals
        4. Detects questions
        5. Calculates processing time
        6. Returns complete EmotionAnalysis object
        
        Args:
            message: User message text to analyze
            
        Returns:
            EmotionAnalysis object with all fields populated
            
        Example:
            >>> pipeline = EmotionPipeline()
            >>> result = pipeline.analyze("I love this! How much?")
            >>> result.sentiment
            <SentimentLabel.POSITIVE: 'positive'>
            >>> result.emotion
            <EmotionLabel.JOY: 'joy'>
            >>> result.purchase_intent_score
            8
        """
        start_time = time.time()
        
        # Run VADER sentiment analysis
        vader_result = self.vader.analyze(message)
        vader_compound = vader_result['compound']
        vader_pos = vader_result['pos']
        vader_neg = vader_result['neg']
        vader_neu = vader_result['neu']
        sentiment = vader_result['sentiment']
        
        # Run BERT emotion classification
        bert_result = self.bert.classify(message)
        emotion_str = bert_result['emotion']
        emotion_confidence = bert_result['confidence']
        
        # Map BERT emotion string to EmotionLabel enum
        emotion = self._map_emotion_label(emotion_str)
        
        # Run purchase intent scoring
        purchase_intent_score = self.intent.score(
            message=message,
            sentiment_compound=vader_compound,
            emotion=emotion_str
        )
        
        # Detect questions
        contains_question = '?' in message
        
        # Calculate metadata
        message_length = len(message)
        processing_time_ms = (time.time() - start_time) * 1000
        
        # Build and return EmotionAnalysis object
        return EmotionAnalysis(
            # Input
            message=message,
            timestamp=datetime.now(),
            
            # VADER results
            vader_compound=vader_compound,
            vader_pos=vader_pos,
            vader_neg=vader_neg,
            vader_neu=vader_neu,
            
            # Sentiment classification
            sentiment=sentiment,
            
            # BERT emotion classification
            emotion=emotion,
            emotion_confidence=emotion_confidence,
            
            # Purchase intent
            purchase_intent_score=purchase_intent_score,
            
            # Metadata
            contains_question=contains_question,
            message_length=message_length,
            processing_time_ms=processing_time_ms
        )
    
    def analyze_batch(self, messages: List[str]) -> List[EmotionAnalysis]:
        """
        Analyze multiple messages efficiently.
        
        Currently processes messages sequentially. Could be optimized with
        batching for BERT in the future.
        
        Args:
            messages: List of message texts to analyze
            
        Returns:
            List of EmotionAnalysis objects, one per message
            
        Example:
            >>> pipeline = EmotionPipeline()
            >>> messages = ["Hello!", "I love this!", "How much?"]
            >>> results = pipeline.analyze_batch(messages)
            >>> len(results)
            3
        """
        results = []
        for message in messages:
            result = self.analyze(message)
            results.append(result)
        return results
    
    def _map_emotion_label(self, emotion_str: str) -> EmotionLabel:
        """
        Map BERT emotion string to EmotionLabel enum.
        
        The BERT model returns emotions as strings. We need to map them
        to our EmotionLabel enum for type safety.
        
        Args:
            emotion_str: Emotion string from BERT (e.g., "joy", "anger")
            
        Returns:
            EmotionLabel enum value
            
        Raises:
            ValueError: If emotion string doesn't map to known label
        """
        # Create mapping from string to enum
        emotion_map = {
            'anger': EmotionLabel.ANGER,
            'disgust': EmotionLabel.DISGUST,
            'fear': EmotionLabel.FEAR,
            'joy': EmotionLabel.JOY,
            'neutral': EmotionLabel.NEUTRAL,
            'sadness': EmotionLabel.SADNESS,
            'surprise': EmotionLabel.SURPRISE
        }
        
        # Convert to lowercase for case-insensitive matching
        emotion_lower = emotion_str.lower()
        
        if emotion_lower not in emotion_map:
            # Default to neutral if unknown emotion
            return EmotionLabel.NEUTRAL
        
        return emotion_map[emotion_lower]
