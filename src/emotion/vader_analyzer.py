"""VADER sentiment analyzer for emotion detection pipeline."""

from typing import Dict, Any
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .config import EmotionConfig, SentimentLabel


class VADERAnalyzer:
    """VADER (Valence Aware Dictionary and sEntiment Reasoner) sentiment analyzer.
    
    VADER is specifically attuned to sentiments expressed in social media and works
    well with emojis, slang, and informal text.
    
    Attributes:
        config: Emotion configuration with thresholds
        analyzer: VADER sentiment intensity analyzer
    """
    
    def __init__(self, config: EmotionConfig):
        """Initialize VADER analyzer with configuration.
        
        Args:
            config: EmotionConfig with sentiment thresholds
        """
        self.config = config
        self.analyzer = SentimentIntensityAnalyzer()
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """Analyze sentiment of text using VADER.
        
        Args:
            text: Input text to analyze
            
        Returns:
            Dictionary containing:
                - compound: Overall sentiment score (-1 to +1)
                - pos: Positive sentiment ratio (0 to 1)
                - neg: Negative sentiment ratio (0 to 1)
                - neu: Neutral sentiment ratio (0 to 1)
                - sentiment: Classified sentiment label
                
        Example:
            >>> analyzer = VADERAnalyzer(EmotionConfig())
            >>> result = analyzer.analyze("I love this!")
            >>> result['compound']
            0.6369
            >>> result['sentiment']
            <SentimentLabel.POSITIVE: 'positive'>
        """
        # Get VADER scores
        scores = self.analyzer.polarity_scores(text)
        
        # Extract individual scores
        compound = scores['compound']
        pos = scores['pos']
        neg = scores['neg']
        neu = scores['neu']
        
        # Classify sentiment based on compound score
        sentiment = self._classify_sentiment(compound)
        
        return {
            'compound': compound,
            'pos': pos,
            'neg': neg,
            'neu': neu,
            'sentiment': sentiment
        }
    
    def _classify_sentiment(self, compound: float) -> SentimentLabel:
        """Classify sentiment based on compound score and config thresholds.
        
        VADER compound scores range from -1 (most negative) to +1 (most positive).
        
        Classification thresholds:
            - >= vader_pos_threshold: positive/very_positive
            - <= vader_neg_threshold: negative/very_negative
            - between: neutral
            
        Args:
            compound: VADER compound score (-1 to +1)
            
        Returns:
            SentimentLabel enum value
        """
        pos_threshold = self.config.vader_pos_threshold
        neg_threshold = self.config.vader_neg_threshold
        
        if compound >= pos_threshold:
            # Further classify positive sentiment
            if compound >= 0.5:
                return SentimentLabel.VERY_POSITIVE
            else:
                return SentimentLabel.POSITIVE
        elif compound <= neg_threshold:
            # Further classify negative sentiment
            if compound <= -0.5:
                return SentimentLabel.VERY_NEGATIVE
            else:
                return SentimentLabel.NEGATIVE
        else:
            return SentimentLabel.NEUTRAL
