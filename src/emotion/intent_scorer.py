"""
Purchase intent scoring based on message content and sentiment.
"""
import re
from typing import Optional


class IntentScorer:
    """
    Scores user messages for purchase intent on a scale of 0-10.
    
    Uses a weighted combination of:
    - Keyword analysis (high/medium intent words)
    - Sentiment analysis
    - Question detection
    """
    
    # High-intent keywords (strong purchase signals)
    HIGH_INTENT_KEYWORDS = {
        'buy', 'purchase', 'price', 'cost', 'custom', 'ppv', 
        'order', 'pay', 'subscription', 'subscribe', 'tip',
        'unlock', 'exclusive', 'premium', 'dm', 'private'
    }
    
    # Medium-intent keywords (interest signals)
    MEDIUM_INTENT_KEYWORDS = {
        'love', 'amazing', 'hot', 'more', 'like', 'want',
        'interested', 'show', 'see', 'content', 'video',
        'photo', 'picture', 'sexy', 'beautiful', 'gorgeous'
    }
    
    # Scoring weights
    KEYWORD_WEIGHT = 0.3
    SENTIMENT_WEIGHT = 0.4
    QUESTION_WEIGHT = 0.3
    
    def score(self, message: str, sentiment_compound: float, emotion: str) -> int:
        """
        Calculate purchase intent score for a message.
        
        Args:
            message: The user's message text
            sentiment_compound: Sentiment compound score (-1 to 1)
            emotion: Detected emotion (joy, anger, neutral, etc.)
            
        Returns:
            Intent score from 0 (no intent) to 10 (very high intent)
        """
        # Calculate component scores (each 0-1)
        keyword_score = self._score_keywords(message)
        sentiment_score = self._score_sentiment(sentiment_compound, emotion)
        question_score = self._score_questions(message)
        
        # Weighted combination
        combined_score = (
            keyword_score * self.KEYWORD_WEIGHT +
            sentiment_score * self.SENTIMENT_WEIGHT +
            question_score * self.QUESTION_WEIGHT
        )
        
        # Scale to 0-10 and round to integer
        final_score = int(round(combined_score * 10))
        
        # Clamp to valid range
        return max(0, min(10, final_score))
    
    def _score_keywords(self, message: str) -> float:
        """
        Score based on presence of purchase intent keywords.
        
        Args:
            message: The message text
            
        Returns:
            Score from 0 to 1
        """
        message_lower = message.lower()
        words = set(re.findall(r'\b\w+\b', message_lower))
        
        # Count keyword matches
        high_matches = len(words & self.HIGH_INTENT_KEYWORDS)
        medium_matches = len(words & self.MEDIUM_INTENT_KEYWORDS)
        
        # High intent keywords worth more
        score = high_matches * 0.3 + medium_matches * 0.1
        
        # Cap at 1.0
        return min(1.0, score)
    
    def _score_sentiment(self, compound: float, emotion: str) -> float:
        """
        Score based on sentiment and emotion.
        
        Positive sentiment/emotions indicate higher engagement and intent.
        
        Args:
            compound: Sentiment compound score (-1 to 1)
            emotion: Detected emotion
            
        Returns:
            Score from 0 to 1
        """
        # Base score from sentiment compound (map -1:1 to 0:1)
        sentiment_score = (compound + 1) / 2
        
        # Boost for positive emotions
        positive_emotions = {'joy', 'love', 'excitement', 'surprise'}
        if emotion in positive_emotions:
            sentiment_score = min(1.0, sentiment_score * 1.2)
        
        # Penalty for negative emotions
        negative_emotions = {'anger', 'sadness', 'disgust', 'fear'}
        if emotion in negative_emotions:
            sentiment_score *= 0.7
        
        return sentiment_score
    
    def _score_questions(self, message: str) -> float:
        """
        Score based on whether message contains questions.
        
        Questions indicate curiosity and engagement, suggesting higher intent.
        
        Args:
            message: The message text
            
        Returns:
            Score from 0 to 1
        """
        # Check for question marks
        has_question_mark = '?' in message
        
        # Check for question words - but be careful about casual greetings
        question_words = {'what', 'when', 'where', 'why', 
                         'can', 'could', 'would', 'should', 'does'}
        message_lower = message.lower()
        words = re.findall(r'\b\w+\b', message_lower)
        
        # "how are you" is a greeting, not a purchase question
        if 'how' in message_lower and 'are' in message_lower and 'you' in message_lower:
            has_question_word = False
        else:
            has_question_word = any(word in question_words for word in words[:3])  # Check first 3 words
        
        # Questions get 0.7, non-questions get 0.3 (baseline engagement)
        if has_question_mark or has_question_word:
            return 0.7
        else:
            return 0.3
