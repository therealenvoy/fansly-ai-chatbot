# Emotion Detection System - Complete Documentation

## Overview

The Emotion Detection System is a comprehensive AI-powered analysis tool that detects:
- **Sentiment** (very negative → very positive)
- **Emotions** (anger, disgust, fear, joy, neutral, sadness, surprise)
- **Purchase Intent** (0-10 score)
- **Emotional Arcs** (multi-message conversation tracking)

## Architecture

```
┌─────────────────────────────────────────────────┐
│           Emotion Detection Pipeline             │
│                                                   │
│  ┌──────────────┐  ┌─────────────────────────┐  │
│  │ VADER        │  │ BERT Emotion Classifier │  │
│  │ Sentiment    │  │ (7 emotion categories)  │  │
│  │ Analyzer     │  │                         │  │
│  └──────────────┘  └─────────────────────────┘  │
│         │                      │                 │
│         └──────────┬───────────┘                 │
│                    ▼                             │
│         ┌────────────────────┐                   │
│         │  Intent Scorer     │                   │
│         │  (Purchase Intent) │                   │
│         └────────────────────┘                   │
│                    │                             │
│                    ▼                             │
│         ┌────────────────────┐                   │
│         │ EmotionAnalysis    │                   │
│         │ (Complete Result)  │                   │
│         └────────────────────┘                   │
└─────────────────────────────────────────────────┘
```

## Core Components

### 1. EmotionPipeline

The main entry point for single-message analysis.

**Features:**
- VADER sentiment analysis (optimized for social media text)
- BERT-based emotion classification (7 emotions)
- Purchase intent scoring
- Question detection
- Performance metrics

**Usage:**
```python
from src.emotion.pipeline import EmotionPipeline

pipeline = EmotionPipeline()
result = pipeline.analyze("I love this! How much does it cost?")

print(f"Sentiment: {result.sentiment.value}")
print(f"Emotion: {result.emotion.value}")
print(f"Purchase Intent: {result.purchase_intent_score}/10")
```

### 2. EmotionalArcTracker

Tracks emotional state across multi-message conversations.

**Features:**
- Sentiment trend detection (warming, cooling, neutral)
- Purchase readiness scoring
- Warning signal detection (disengagement, negative patterns)
- Conversation history tracking

**Usage:**
```python
from src.emotion.arc_tracker import EmotionalArcTracker

tracker = EmotionalArcTracker(
    subscriber_id="user123",
    conversation_id="conv456"
)

# Add messages to conversation
tracker.update("Hi! What do you offer?")
tracker.update("That sounds interesting!")
tracker.update("How much does it cost?")

# Get emotional arc analysis
arc = tracker.get_arc()
print(f"Sentiment Trend: {arc.sentiment_trend.value}")
print(f"Purchase Readiness: {arc.purchase_readiness_index:.2f}")
print(f"Is Engaged: {arc.is_engaged}")
```

### 3. REST API

FastAPI-based HTTP API for remote access.

**Endpoints:**
- `POST /analyze` - Analyze single message
- `POST /analyze/batch` - Analyze multiple messages
- `GET /health` - Health check

**Example:**
```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to buy this now!"}'
```

### 4. CLI

Command-line interface for local analysis and testing.

**Commands:**
```bash
# Analyze single message
python -m src.emotion.cli analyze "I love this!"

# Analyze batch from file
python -m src.emotion.cli batch messages.txt

# Run demonstration
python -m src.emotion.cli demo
```

## Data Models

### EmotionAnalysis

Single message analysis result:

```python
{
    "message": "I love this! How much?",
    "timestamp": "2026-07-24T15:00:00",
    
    # VADER scores
    "vader_compound": 0.6369,
    "vader_pos": 0.406,
    "vader_neg": 0.0,
    "vader_neu": 0.594,
    
    # Classifications
    "sentiment": "very_positive",  # very_negative|negative|neutral|positive|very_positive
    "emotion": "joy",              # anger|disgust|fear|joy|neutral|sadness|surprise
    "emotion_confidence": 0.85,
    
    # Purchase intent
    "purchase_intent_score": 8,    # 0-10
    
    # Metadata
    "contains_question": true,
    "message_length": 22,
    "processing_time_ms": 45.2
}
```

### EmotionalArc

Conversation-level emotional tracking:

```python
{
    "subscriber_id": "user123",
    "conversation_id": "conv456",
    "messages": [...],              # List of EmotionAnalysis objects
    
    # Arc metrics
    "average_sentiment": 0.45,      # -1.0 to 1.0
    "sentiment_trend": "warming",   # warming|cooling|neutral
    "dominant_emotion": "joy",
    
    # Engagement signals
    "is_engaged": true,
    "is_cooling_off": false,
    "warning_signals": [],         # ["negative_sentiment", "short_responses", etc]
    
    # Purchase readiness
    "purchase_readiness_index": 0.75,  # 0.0 to 1.0
    
    # Timestamps
    "first_message_at": "2026-07-24T14:00:00",
    "last_message_at": "2026-07-24T15:00:00"
}
```

## Configuration

Located in `src/emotion/config.py`:

```python
from src.emotion.config import EmotionConfig

config = EmotionConfig(
    # Sentiment thresholds
    very_negative_threshold=-0.5,
    negative_threshold=-0.1,
    positive_threshold=0.1,
    very_positive_threshold=0.5,
    
    # BERT model
    bert_model_name="SamLowe/roberta-base-go_emotions",
    bert_device="cpu",  # or "cuda" for GPU
    
    # Arc tracking
    arc_window_size=3,  # Last N messages for trend
    warming_threshold=0.15,
    cooling_threshold=-0.15
)

pipeline = EmotionPipeline(config)
```

## Performance

Typical processing times (CPU):
- Single message analysis: ~40-50ms
- VADER only: ~1-2ms (very fast)
- BERT only: ~30-40ms (accurate emotion detection)
- Full pipeline: ~45ms (combined)

Optimization tips:
- Use GPU for BERT (`bert_device="cuda"`) for large batches
- Cache pipeline instance (models loaded once)
- Use batch processing for multiple messages

## Advanced Usage

### Custom Emotion Keywords

Add domain-specific keywords for better intent scoring:

```python
from src.emotion.intent_scorer import IntentScorer

scorer = IntentScorer()
scorer.PRICING_KEYWORDS.add("subscription")
scorer.PURCHASE_ACTION_KEYWORDS.add("join")
```

### Sentiment Trend Analysis

```python
tracker = EmotionalArcTracker("user123", "conv456")

# Add conversation messages
for msg in messages:
    tracker.update(msg)

# Check for cooling
if tracker.arc.is_cooling_off:
    print("Warning: User is losing interest!")
    print(f"Signals: {tracker.arc.warning_signals}")
    
# Check purchase readiness
if tracker.arc.purchase_readiness_index > 0.7:
    print("User is ready to buy!")
```

### API Integration

```python
import requests

response = requests.post(
    "http://localhost:8000/analyze",
    json={"message": "I want to buy this!"}
)

data = response.json()
if data['purchase_intent_score'] >= 7:
    # Send pricing information
    pass
```

## Testing

Run the test suite:

```bash
# All tests
python3 -m pytest tests/ -v

# Integration tests only
python3 -m pytest tests/integration/ -v

# Unit tests only
python3 -m pytest tests/emotion/ -v

# Specific test
python3 -m pytest tests/emotion/test_pipeline.py -v
```

Test coverage: **46 tests, 100% pass rate**
- 34 unit tests
- 12 integration tests

## Troubleshooting

### Issue: Slow BERT loading

**Solution:** BERT model downloads on first use. Subsequent runs are fast.

### Issue: Low purchase intent scores

**Solution:** Adjust thresholds in IntentScorer or add custom keywords.

### Issue: Incorrect emotion classification

**Solution:** BERT model may need fine-tuning for your specific domain.

## API Reference

See [docs/api/EMOTION_API.md](api/EMOTION_API.md) for complete REST API documentation.

## Examples

See [docs/examples/emotion_usage.py](examples/emotion_usage.py) for comprehensive code examples.

## License

Part of the Fansly AI Chatbot project.
