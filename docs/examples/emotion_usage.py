"""
Comprehensive examples for the Emotion Detection System.

This file demonstrates all major features and use cases.
"""

# ============================================================================
# Example 1: Basic Single Message Analysis
# ============================================================================

from src.emotion.pipeline import EmotionPipeline

def example_basic_analysis():
    """Analyze a single message."""
    print("=" * 60)
    print("Example 1: Basic Single Message Analysis")
    print("=" * 60)
    
    pipeline = EmotionPipeline()
    
    result = pipeline.analyze("I love this! How much does it cost?")
    
    print(f"Message: {result.message}")
    print(f"Sentiment: {result.sentiment.value}")
    print(f"Emotion: {result.emotion.value} (confidence: {result.emotion_confidence:.2%})")
    print(f"Purchase Intent: {result.purchase_intent_score}/10")
    print(f"Contains Question: {result.contains_question}")
    print(f"VADER Compound: {result.vader_compound:.3f}")
    print(f"Processing Time: {result.processing_time_ms:.2f}ms")
    print()


# ============================================================================
# Example 2: Batch Processing
# ============================================================================

def example_batch_processing():
    """Analyze multiple messages efficiently."""
    print("=" * 60)
    print("Example 2: Batch Processing")
    print("=" * 60)
    
    pipeline = EmotionPipeline()
    
    messages = [
        "Hello! Nice to meet you",
        "I absolutely love this product! 😍",
        "This is terrible and disappointing",
        "How much does it cost?",
        "I want to buy it now!",
    ]
    
    results = pipeline.analyze_batch(messages)
    
    print(f"Analyzed {len(results)} messages:\n")
    for i, result in enumerate(results, 1):
        print(f"{i}. {result.message[:40]}")
        print(f"   └─ {result.sentiment.value} | {result.emotion.value} | Intent: {result.purchase_intent_score}/10")
    print()


# ============================================================================
# Example 3: Conversational Arc Tracking
# ============================================================================

from src.emotion.arc_tracker import EmotionalArcTracker

def example_arc_tracking():
    """Track emotional state across a conversation."""
    print("=" * 60)
    print("Example 3: Conversational Arc Tracking")
    print("=" * 60)
    
    tracker = EmotionalArcTracker(
        subscriber_id="user_001",
        conversation_id="conv_001"
    )
    
    # Simulate a conversation
    conversation = [
        "Hi! What kind of content do you have?",
        "That sounds interesting!",
        "I love that kind of stuff! 😍",
        "How much does it cost?",
        "I want to buy that now!"
    ]
    
    print("Conversation:")
    for i, message in enumerate(conversation, 1):
        result = tracker.update(message)
        print(f"{i}. User: {message}")
        print(f"   └─ Sentiment: {result.sentiment.value} | Intent: {result.purchase_intent_score}/10")
    
    # Get emotional arc summary
    arc = tracker.get_arc()
    
    print(f"\nConversation Summary:")
    print(f"  Total Messages: {len(arc.messages)}")
    print(f"  Average Sentiment: {arc.average_sentiment:.3f}")
    print(f"  Sentiment Trend: {arc.sentiment_trend.value}")
    print(f"  Dominant Emotion: {arc.dominant_emotion.value}")
    print(f"  Is Engaged: {arc.is_engaged}")
    print(f"  Is Cooling Off: {arc.is_cooling_off}")
    print(f"  Purchase Readiness: {arc.purchase_readiness_index:.2%}")
    print(f"  Warning Signals: {arc.warning_signals or 'None'}")
    print()


# ============================================================================
# Example 4: Detecting Purchase Readiness
# ============================================================================

def example_purchase_readiness():
    """Identify when a user is ready to make a purchase."""
    print("=" * 60)
    print("Example 4: Detecting Purchase Readiness")
    print("=" * 60)
    
    tracker = EmotionalArcTracker(
        subscriber_id="user_002",
        conversation_id="conv_002"
    )
    
    messages = [
        "What do you offer?",
        "That's pretty cool!",
        "I really like that",
        "How much is everything?",
        "I definitely want to buy this!"
    ]
    
    for message in messages:
        tracker.update(message)
    
    arc = tracker.get_arc()
    
    print(f"Purchase Readiness Assessment:")
    print(f"  Readiness Index: {arc.purchase_readiness_index:.2%}")
    print(f"  Average Intent Score: {sum(m.purchase_intent_score for m in arc.messages) / len(arc.messages):.1f}/10")
    print(f"  Sentiment Trend: {arc.sentiment_trend.value}")
    
    # Decision logic
    if arc.purchase_readiness_index > 0.7:
        print(f"\n✅ HIGH READINESS - Send pricing and purchase options!")
    elif arc.purchase_readiness_index > 0.4:
        print(f"\n⚠️  MODERATE READINESS - Continue engagement, highlight value")
    else:
        print(f"\n❌ LOW READINESS - Build interest, showcase content")
    print()


# ============================================================================
# Example 5: Detecting Disengagement
# ============================================================================

def example_disengagement_detection():
    """Detect when a user is losing interest."""
    print("=" * 60)
    print("Example 5: Detecting Disengagement")
    print("=" * 60)
    
    tracker = EmotionalArcTracker(
        subscriber_id="user_003",
        conversation_id="conv_003"
    )
    
    # Simulate cooling conversation
    messages = [
        "Hi! Your content looks great!",
        "Tell me more",
        "ok",
        "sure",
        "maybe"
    ]
    
    print("Conversation:")
    for i, message in enumerate(messages, 1):
        result = tracker.update(message)
        print(f"{i}. User: {message}")
        print(f"   └─ Length: {result.message_length} chars | Sentiment: {result.sentiment.value}")
    
    arc = tracker.get_arc()
    
    print(f"\nDisengagement Analysis:")
    print(f"  Is Cooling Off: {arc.is_cooling_off}")
    print(f"  Sentiment Trend: {arc.sentiment_trend.value}")
    print(f"  Warning Signals: {arc.warning_signals}")
    
    if arc.is_cooling_off:
        print(f"\n⚠️  WARNING: User is disengaging!")
        print(f"   Recommended actions:")
        print(f"   - Ask engaging questions")
        print(f"   - Share exclusive content preview")
        print(f"   - Offer limited-time deal")
    print()


# ============================================================================
# Example 6: Using the REST API
# ============================================================================

def example_rest_api():
    """Interact with the emotion analysis API."""
    print("=" * 60)
    print("Example 6: Using the REST API")
    print("=" * 60)
    
    import requests
    
    BASE_URL = "http://localhost:8000"
    
    try:
        # Check health
        health = requests.get(f"{BASE_URL}/health", timeout=2)
        print(f"API Health: {health.json()['status']}")
        
        # Analyze single message
        response = requests.post(
            f"{BASE_URL}/analyze",
            json={"message": "I want to buy this now!"},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"\nAPI Analysis Result:")
            print(f"  Sentiment: {data['sentiment']}")
            print(f"  Emotion: {data['emotion']}")
            print(f"  Purchase Intent: {data['purchase_intent_score']}/10")
        
        # Batch analysis
        batch_response = requests.post(
            f"{BASE_URL}/analyze/batch",
            json={"messages": ["Hello!", "I love this!", "How much?"]},
            timeout=10
        )
        
        if batch_response.status_code == 200:
            batch_data = batch_response.json()
            print(f"\nBatch Analysis: {len(batch_data['results'])} messages processed")
    
    except requests.exceptions.ConnectionError:
        print("⚠️  API server not running. Start with: python -m src.emotion.api")
    except Exception as e:
        print(f"⚠️  Error: {e}")
    
    print()


# ============================================================================
# Example 7: Using the CLI
# ============================================================================

def example_cli_usage():
    """Demonstrate CLI usage."""
    print("=" * 60)
    print("Example 7: Using the CLI")
    print("=" * 60)
    
    print("Command-line interface commands:\n")
    
    print("1. Analyze single message:")
    print("   python -m src.emotion.cli analyze \"I love this product!\"\n")
    
    print("2. Analyze with JSON output:")
    print("   python -m src.emotion.cli analyze \"How much?\" --json\n")
    
    print("3. Batch process from file:")
    print("   python -m src.emotion.cli batch messages.txt\n")
    
    print("4. Run demonstration:")
    print("   python -m src.emotion.cli demo\n")
    
    print("5. Get help:")
    print("   python -m src.emotion.cli --help\n")


# ============================================================================
# Example 8: Custom Configuration
# ============================================================================

from src.emotion.config import EmotionConfig

def example_custom_config():
    """Use custom configuration for emotion analysis."""
    print("=" * 60)
    print("Example 8: Custom Configuration")
    print("=" * 60)
    
    # Create custom configuration
    custom_config = EmotionConfig(
        # Adjust sentiment thresholds
        very_negative_threshold=-0.6,
        negative_threshold=-0.2,
        positive_threshold=0.2,
        very_positive_threshold=0.6,
        
        # BERT configuration
        bert_device="cpu",  # Use "cuda" for GPU
        
        # Arc tracking settings
        arc_window_size=5,  # Use last 5 messages for trend
        warming_threshold=0.2,
        cooling_threshold=-0.2
    )
    
    # Use custom config
    pipeline = EmotionPipeline(config=custom_config)
    tracker = EmotionalArcTracker(
        subscriber_id="user_004",
        conversation_id="conv_004",
        config=custom_config
    )
    
    result = pipeline.analyze("This is good!")
    
    print(f"Using custom configuration:")
    print(f"  Sentiment: {result.sentiment.value}")
    print(f"  (with custom thresholds)")
    print()


# ============================================================================
# Example 9: Performance Benchmarking
# ============================================================================

import time

def example_performance_benchmark():
    """Benchmark pipeline performance."""
    print("=" * 60)
    print("Example 9: Performance Benchmarking")
    print("=" * 60)
    
    pipeline = EmotionPipeline()
    
    test_messages = [
        "I love this!",
        "This is terrible",
        "How much does it cost?",
        "I want to buy it now!",
        "Maybe later"
    ]
    
    # Warm up (load models)
    pipeline.analyze("warmup")
    
    # Benchmark single messages
    start = time.time()
    for _ in range(10):
        for msg in test_messages:
            pipeline.analyze(msg)
    single_time = (time.time() - start) * 1000 / (10 * len(test_messages))
    
    print(f"Performance Metrics:")
    print(f"  Average time per message: {single_time:.2f}ms")
    print(f"  Throughput: {1000/single_time:.1f} messages/second")
    print(f"  Total messages in test: {10 * len(test_messages)}")
    print()


# ============================================================================
# Example 10: Complete Sales Conversation
# ============================================================================

def example_complete_sales_conversation():
    """Full example of a sales conversation with analysis and recommendations."""
    print("=" * 60)
    print("Example 10: Complete Sales Conversation")
    print("=" * 60)
    
    tracker = EmotionalArcTracker(
        subscriber_id="user_005",
        conversation_id="conv_005"
    )
    
    conversation = [
        ("User", "Hi! What kind of exclusive content do you have?"),
        ("Bot", "I have premium photos and videos just for subscribers!"),
        ("User", "That sounds interesting! Tell me more"),
        ("Bot", "I post daily content - photoshoots, behind-the-scenes, and custom requests"),
        ("User", "Wow, I love that kind of stuff! 😍"),
        ("Bot", "I'm glad you're interested! Would you like to see a preview?"),
        ("User", "Yes please!"),
        ("Bot", "Check your DMs for a sneak peek 😉"),
        ("User", "OMG this is amazing! How much does it cost to unlock everything?"),
        ("Bot", "It's $19.99/month for full access. Special offer: 20% off first month!"),
        ("User", "I definitely want to buy that!"),
    ]
    
    print("Conversation Flow:\n")
    
    for i, (speaker, message) in enumerate(conversation, 1):
        if speaker == "User":
            result = tracker.update(message)
            arc = tracker.get_arc()
            
            print(f"{i}. {speaker}: {message}")
            print(f"   Analysis: {result.sentiment.value} | Intent: {result.purchase_intent_score}/10")
            print(f"   Arc: Trend={arc.sentiment_trend.value}, Readiness={arc.purchase_readiness_index:.2%}")
            
            # Generate recommendation
            if arc.purchase_readiness_index > 0.7:
                print(f"   💡 Recommendation: Send pricing and purchase link!")
            elif arc.purchase_readiness_index > 0.4:
                print(f"   💡 Recommendation: Share preview or special offer")
            elif arc.is_cooling_off:
                print(f"   ⚠️  Warning: Cooling off - re-engage with question")
            
            print()
        else:
            print(f"{i}. {speaker}: {message}\n")
    
    # Final summary
    arc = tracker.get_arc()
    print(f"Final Conversation Summary:")
    print(f"  ✅ Engagement: {'High' if arc.is_engaged else 'Low'}")
    print(f"  ✅ Purchase Readiness: {arc.purchase_readiness_index:.2%}")
    print(f"  ✅ Sentiment Trend: {arc.sentiment_trend.value}")
    print(f"  ✅ Conversion Probability: {'High' if arc.purchase_readiness_index > 0.6 else 'Moderate'}")
    print()


# ============================================================================
# Main: Run All Examples
# ============================================================================

if __name__ == "__main__":
    examples = [
        example_basic_analysis,
        example_batch_processing,
        example_arc_tracking,
        example_purchase_readiness,
        example_disengagement_detection,
        example_rest_api,
        example_cli_usage,
        example_custom_config,
        example_performance_benchmark,
        example_complete_sales_conversation,
    ]
    
    print("\n" + "=" * 60)
    print("EMOTION DETECTION SYSTEM - COMPREHENSIVE EXAMPLES")
    print("=" * 60 + "\n")
    
    for i, example_func in enumerate(examples, 1):
        try:
            example_func()
            if i < len(examples):
                input("Press Enter to continue to next example...")
                print("\n")
        except KeyboardInterrupt:
            print("\n\nExamples interrupted by user.")
            break
        except Exception as e:
            print(f"⚠️  Error in example: {e}\n")
            continue
    
    print("=" * 60)
    print("All examples complete!")
    print("=" * 60)
