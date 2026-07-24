"""
FastAPI REST endpoint for emotion analysis.

Provides HTTP API for analyzing subscriber messages for emotion,
sentiment, and purchase intent.

Endpoints:
    POST /analyze - Analyze single message
    POST /analyze/batch - Analyze multiple messages
    GET /health - Health check
"""
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from .pipeline import EmotionPipeline
from .models import EmotionAnalysis


# Pydantic models for request/response
class AnalyzeRequest(BaseModel):
    """Request model for single message analysis"""
    message: str = Field(..., min_length=1, description="Message text to analyze")
    
    @field_validator('message')
    @classmethod
    def validate_message(cls, v: str) -> str:
        """Validate message is not empty after stripping"""
        if not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v


class AnalyzeResponse(BaseModel):
    """Response model wrapping EmotionAnalysis"""
    # We'll use EmotionAnalysis directly as it's already a Pydantic model
    pass


class BatchAnalyzeRequest(BaseModel):
    """Request model for batch message analysis"""
    messages: List[str] = Field(..., min_length=1, description="List of messages to analyze")
    
    @field_validator('messages')
    @classmethod
    def validate_messages(cls, v: List[str]) -> List[str]:
        """Validate each message is not empty"""
        if not v:
            raise ValueError("Messages list cannot be empty")
        for msg in v:
            if not msg.strip():
                raise ValueError("Messages cannot contain empty or whitespace-only strings")
        return v


class BatchAnalyzeResponse(BaseModel):
    """Response model for batch analysis"""
    results: List[EmotionAnalysis] = Field(..., description="List of emotion analysis results")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")


# Initialize FastAPI app
app = FastAPI(
    title="Emotion Analysis API",
    description="REST API for analyzing message emotion, sentiment, and purchase intent",
    version="1.0.0"
)

# Global pipeline instance (singleton pattern)
# This is initialized once when the API starts
_pipeline: EmotionPipeline = None


def get_pipeline() -> EmotionPipeline:
    """
    Get or create the global emotion pipeline instance.
    
    Uses singleton pattern to avoid loading models multiple times.
    
    Returns:
        EmotionPipeline instance
    """
    global _pipeline
    if _pipeline is None:
        _pipeline = EmotionPipeline()
    return _pipeline


@app.post("/analyze", response_model=EmotionAnalysis, status_code=200)
async def analyze_message(request: AnalyzeRequest) -> EmotionAnalysis:
    """
    Analyze a single message for emotion, sentiment, and purchase intent.
    
    Args:
        request: AnalyzeRequest with message text
        
    Returns:
        EmotionAnalysis object with all analysis results
        
    Example:
        POST /analyze
        {
            "message": "I love this product! How much does it cost?"
        }
        
        Returns:
        {
            "message": "I love this product! How much does it cost?",
            "sentiment": "positive",
            "emotion": "joy",
            "purchase_intent_score": 8,
            ...
        }
    """
    try:
        pipeline = get_pipeline()
        result = pipeline.analyze(request.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/analyze/batch", response_model=BatchAnalyzeResponse, status_code=200)
async def analyze_batch(request: BatchAnalyzeRequest) -> BatchAnalyzeResponse:
    """
    Analyze multiple messages in batch.
    
    Args:
        request: BatchAnalyzeRequest with list of messages
        
    Returns:
        BatchAnalyzeResponse with list of EmotionAnalysis results
        
    Example:
        POST /analyze/batch
        {
            "messages": [
                "Hello there!",
                "I love this!",
                "How much does this cost?"
            ]
        }
        
        Returns:
        {
            "results": [
                { "message": "Hello there!", "sentiment": "positive", ... },
                { "message": "I love this!", "sentiment": "very_positive", ... },
                { "message": "How much does this cost?", "sentiment": "neutral", ... }
            ]
        }
    """
    try:
        pipeline = get_pipeline()
        results = pipeline.analyze_batch(request.messages)
        return BatchAnalyzeResponse(results=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch analysis failed: {str(e)}")


@app.get("/health", response_model=HealthResponse, status_code=200)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns:
        HealthResponse indicating service is running
        
    Example:
        GET /health
        
        Returns:
        {
            "status": "ok",
            "service": "emotion-analysis-api"
        }
    """
    return HealthResponse(
        status="ok",
        service="emotion-analysis-api"
    )
