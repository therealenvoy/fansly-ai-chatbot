# Emotion Analysis REST API Reference

## Base URL

```
http://localhost:8000
```

## Authentication

Currently no authentication required (development mode).

## Endpoints

### POST /analyze

Analyze a single message for emotion, sentiment, and purchase intent.

**Request:**

```http
POST /analyze HTTP/1.1
Content-Type: application/json

{
  "message": "I love this! How much does it cost?"
}
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| message | string | Yes | Message text to analyze (min 1 character) |

**Response:**

```json
{
  "message": "I love this! How much does it cost?",
  "timestamp": "2026-07-24T15:30:00.123456",
  "vader_compound": 0.6369,
  "vader_pos": 0.406,
  "vader_neg": 0.0,
  "vader_neu": 0.594,
  "sentiment": "very_positive",
  "emotion": "joy",
  "emotion_confidence": 0.8532,
  "purchase_intent_score": 8,
  "contains_question": true,
  "message_length": 33,
  "processing_time_ms": 45.23
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| message | string | Original message text |
| timestamp | datetime | Analysis timestamp (ISO 8601) |
| vader_compound | float | VADER compound score (-1.0 to 1.0) |
| vader_pos | float | VADER positive score (0.0 to 1.0) |
| vader_neg | float | VADER negative score (0.0 to 1.0) |
| vader_neu | float | VADER neutral score (0.0 to 1.0) |
| sentiment | string | Sentiment label: `very_negative`, `negative`, `neutral`, `positive`, `very_positive` |
| emotion | string | Emotion label: `anger`, `disgust`, `fear`, `joy`, `neutral`, `sadness`, `surprise` |
| emotion_confidence | float | BERT confidence score (0.0 to 1.0) |
| purchase_intent_score | integer | Purchase intent score (0-10) |
| contains_question | boolean | True if message contains '?' |
| message_length | integer | Length of message in characters |
| processing_time_ms | float | Processing time in milliseconds |

**Status Codes:**

- `200 OK` - Analysis successful
- `422 Unprocessable Entity` - Invalid request (empty message, etc.)
- `500 Internal Server Error` - Analysis failed

**Example cURL:**

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -d '{"message": "I want to buy this now!"}'
```

**Example Python:**

```python
import requests

response = requests.post(
    "http://localhost:8000/analyze",
    json={"message": "I want to buy this now!"}
)

data = response.json()
print(f"Sentiment: {data['sentiment']}")
print(f"Purchase Intent: {data['purchase_intent_score']}/10")
```

---

### POST /analyze/batch

Analyze multiple messages in a single request.

**Request:**

```http
POST /analyze/batch HTTP/1.1
Content-Type: application/json

{
  "messages": [
    "Hello there!",
    "I love this product!",
    "How much does it cost?"
  ]
}
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| messages | array[string] | Yes | List of messages to analyze (min 1 message) |

**Response:**

```json
{
  "results": [
    {
      "message": "Hello there!",
      "sentiment": "positive",
      "emotion": "joy",
      ...
    },
    {
      "message": "I love this product!",
      "sentiment": "very_positive",
      "emotion": "joy",
      ...
    },
    {
      "message": "How much does it cost?",
      "sentiment": "neutral",
      "emotion": "surprise",
      ...
    }
  ]
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| results | array[EmotionAnalysis] | List of analysis results, one per message |

Each result contains the same fields as the single `/analyze` endpoint.

**Status Codes:**

- `200 OK` - Batch analysis successful
- `422 Unprocessable Entity` - Invalid request (empty array, empty messages)
- `500 Internal Server Error` - Batch analysis failed

**Example cURL:**

```bash
curl -X POST "http://localhost:8000/analyze/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      "I love this!",
      "This is terrible",
      "How much?"
    ]
  }'
```

**Example Python:**

```python
import requests

messages = [
    "I love this!",
    "This is terrible",
    "How much does it cost?"
]

response = requests.post(
    "http://localhost:8000/analyze/batch",
    json={"messages": messages}
)

data = response.json()
for i, result in enumerate(data['results']):
    print(f"Message {i+1}: {result['sentiment']} ({result['purchase_intent_score']}/10)")
```

---

### GET /health

Health check endpoint to verify the service is running.

**Request:**

```http
GET /health HTTP/1.1
```

**Response:**

```json
{
  "status": "ok",
  "service": "emotion-analysis-api"
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| status | string | Service status: `ok` |
| service | string | Service name: `emotion-analysis-api` |

**Status Codes:**

- `200 OK` - Service is healthy

**Example cURL:**

```bash
curl "http://localhost:8000/health"
```

---

## Error Responses

All endpoints may return errors in the following format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

**Common Error Scenarios:**

### Empty Message

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "message"],
      "msg": "Message cannot be empty or whitespace only"
    }
  ]
}
```

### Missing Required Field

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "message"],
      "msg": "Field required"
    }
  ]
}
```

### Internal Server Error

```json
{
  "detail": "Analysis failed: BERT model not loaded"
}
```

---

## Rate Limits

Currently no rate limits (development mode).

In production, consider implementing:
- Per-IP rate limiting
- API key authentication
- Usage quotas

---

## Data Types

### Sentiment Labels

| Value | Description |
|-------|-------------|
| `very_negative` | VADER compound < -0.5 |
| `negative` | VADER compound between -0.5 and -0.1 |
| `neutral` | VADER compound between -0.1 and 0.1 |
| `positive` | VADER compound between 0.1 and 0.5 |
| `very_positive` | VADER compound > 0.5 |

### Emotion Labels

| Value | Description |
|-------|-------------|
| `anger` | Angry, frustrated, annoyed |
| `disgust` | Disgusted, repulsed |
| `fear` | Fearful, worried, anxious |
| `joy` | Happy, excited, pleased |
| `neutral` | Neutral, no strong emotion |
| `sadness` | Sad, disappointed, unhappy |
| `surprise` | Surprised, amazed, shocked |

### Purchase Intent Scores

| Score | Interpretation |
|-------|----------------|
| 0-2 | Very low intent |
| 3-4 | Low intent |
| 5-6 | Moderate intent |
| 7-8 | High intent |
| 9-10 | Very high intent |

Purchase intent is calculated based on:
- Sentiment polarity
- Pricing keywords (cost, price, buy, etc.)
- Purchase action keywords (want, need, buy, etc.)
- Question presence

---

## OpenAPI / Swagger

Interactive API documentation available at:

```
http://localhost:8000/docs
```

Alternative ReDoc documentation:

```
http://localhost:8000/redoc
```

---

## Examples

### Complete Workflow

```python
import requests

BASE_URL = "http://localhost:8000"

# 1. Check service health
health = requests.get(f"{BASE_URL}/health").json()
print(f"Service: {health['status']}")

# 2. Analyze single message
single = requests.post(
    f"{BASE_URL}/analyze",
    json={"message": "I love this! How much?"}
).json()

print(f"\nSingle Analysis:")
print(f"  Sentiment: {single['sentiment']}")
print(f"  Emotion: {single['emotion']} ({single['emotion_confidence']:.2%})")
print(f"  Purchase Intent: {single['purchase_intent_score']}/10")

# 3. Analyze batch
batch = requests.post(
    f"{BASE_URL}/analyze/batch",
    json={
        "messages": [
            "Hello!",
            "I love this!",
            "How much does it cost?"
        ]
    }
).json()

print(f"\nBatch Analysis ({len(batch['results'])} messages):")
for i, result in enumerate(batch['results'], 1):
    print(f"  {i}. {result['sentiment']} - Intent: {result['purchase_intent_score']}/10")
```

---

## Versioning

Current version: **v1.0.0**

API version is included in the base URL for future versions:
- v1: `/analyze`, `/analyze/batch`, `/health`
- v2 (future): `/v2/analyze`, etc.

---

## Support

For issues or questions:
- See main documentation: [EMOTION_DETECTION.md](../EMOTION_DETECTION.md)
- Run CLI: `python -m src.emotion.cli --help`
- Check examples: [emotion_usage.py](../examples/emotion_usage.py)
