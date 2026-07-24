"""
Tests for the FastAPI emotion analysis REST endpoint.

Tests cover:
- Single message analysis endpoint
- Batch message analysis endpoint
- Input validation and error handling
- Health check endpoint
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime

from src.emotion.api import app
from src.emotion.models import EmotionAnalysis
from src.emotion.config import SentimentLabel, EmotionLabel


@pytest.fixture
def client():
    """Create FastAPI test client"""
    return TestClient(app)


class TestAnalyzeEndpoint:
    """Tests for POST /analyze endpoint (single message)"""
    
    def test_analyze_endpoint_success(self, client):
        """Test successful single message analysis"""
        # Arrange
        request_data = {
            "message": "I love this product! How much does it cost?"
        }
        
        # Act
        response = client.post("/analyze", json=request_data)
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert "message" in data
        assert data["message"] == request_data["message"]
        
        # VADER fields
        assert "vader_compound" in data
        assert -1.0 <= data["vader_compound"] <= 1.0
        assert "vader_pos" in data
        assert "vader_neg" in data
        assert "vader_neu" in data
        
        # Sentiment
        assert "sentiment" in data
        assert data["sentiment"] in ["very_negative", "negative", "neutral", "positive", "very_positive"]
        
        # BERT emotion
        assert "emotion" in data
        assert data["emotion"] in ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
        assert "emotion_confidence" in data
        assert 0.0 <= data["emotion_confidence"] <= 1.0
        
        # Purchase intent
        assert "purchase_intent_score" in data
        assert 0 <= data["purchase_intent_score"] <= 10
        
        # Metadata
        assert "contains_question" in data
        assert data["contains_question"] is True  # message has "?"
        assert "message_length" in data
        assert data["message_length"] > 0
        assert "processing_time_ms" in data
        assert data["processing_time_ms"] > 0
        
        # Timestamp
        assert "timestamp" in data
    
    def test_analyze_endpoint_invalid_request(self, client):
        """Test endpoint with empty message returns 422"""
        # Arrange
        request_data = {
            "message": ""
        }
        
        # Act
        response = client.post("/analyze", json=request_data)
        
        # Assert
        assert response.status_code == 422  # Validation error
    
    def test_analyze_endpoint_missing_message(self, client):
        """Test endpoint with missing message field"""
        # Arrange
        request_data = {}
        
        # Act
        response = client.post("/analyze", json=request_data)
        
        # Assert
        assert response.status_code == 422  # Validation error


class TestAnalyzeBatchEndpoint:
    """Tests for POST /analyze/batch endpoint (multiple messages)"""
    
    def test_analyze_batch_endpoint(self, client):
        """Test batch processing of multiple messages"""
        # Arrange
        request_data = {
            "messages": [
                "Hello there!",
                "I love this!",
                "How much does this cost?"
            ]
        }
        
        # Act
        response = client.post("/analyze/batch", json=request_data)
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert "results" in data
        assert len(data["results"]) == 3
        
        # Check each result has proper structure
        for i, result in enumerate(data["results"]):
            assert "message" in result
            assert result["message"] == request_data["messages"][i]
            assert "sentiment" in result
            assert "emotion" in result
            assert "purchase_intent_score" in result
    
    def test_analyze_batch_empty_list(self, client):
        """Test batch endpoint with empty message list"""
        # Arrange
        request_data = {
            "messages": []
        }
        
        # Act
        response = client.post("/analyze/batch", json=request_data)
        
        # Assert
        assert response.status_code == 422  # Validation error


class TestHealthEndpoint:
    """Tests for GET /health endpoint"""
    
    def test_health_check(self, client):
        """Test health check endpoint returns 200"""
        # Act
        response = client.get("/health")
        
        # Assert
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        assert "service" in data
        assert data["service"] == "emotion-analysis-api"
