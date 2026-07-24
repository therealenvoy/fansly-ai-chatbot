"""
Conversation Data Schema

Use this schema to label your training conversations.
Export your DM history and annotate with these fields.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class PersonalityType(str, Enum):
    """5 subscriber personality types from research"""
    INSTANT_BUYER = "instant_buyer"      # Buys first PPV, eager
    QUIET_LURKER = "quiet_lurker"        # Reads, rarely responds
    ATTENTION_SEEKER = "attention_seeker" # Constant messages, validation
    TESTER = "tester"                     # Questions everything, skeptical
    CHATTY_FAN = "chatty_fan"            # Overly enthusiastic, messages constantly


class ConversationStage(str, Enum):
    """5-Stage Funnel: RAPPORT → TEASE → OFFER → HANDLE → CLOSE"""
    RAPPORT = "rapport"     # Building rapport (1-3 exchanges)
    TEASE = "tease"         # Creating curiosity/demand (2-4 exchanges)
    OFFER = "offer"         # Presenting offer (1-2 exchanges)
    HANDLE = "handle"       # Objection handling (1-3 exchanges)
    CLOSE = "close"         # Closing the sale (1-3 exchanges)


class SentimentLabel(str, Enum):
    """User emotional state"""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class Message(BaseModel):
    """Single message in conversation"""
    timestamp: datetime
    sender: str  # "creator" or "subscriber"
    content: str
    
    # Labels (annotate these)
    sentiment: Optional[SentimentLabel] = None
    purchase_intent_score: Optional[int] = Field(None, ge=0, le=10)  # 0-10 scale
    stage: Optional[ConversationStage] = None
    fan_archetype: Optional[str] = None  # Fan personality archetype tag
    
    # Metadata
    response_time_seconds: Optional[float] = None
    message_length: int = 0
    contains_emoji: bool = False
    is_voice_note: bool = False


class Conversation(BaseModel):
    """Complete conversation thread"""
    conversation_id: str
    subscriber_id: str  # Anonymized
    
    # Messages
    messages: List[Message]
    
    # Conversation-level labels
    personality_type: Optional[PersonalityType] = None
    outcome_purchased: bool = False
    purchase_amount: Optional[float] = None
    purchase_timestamp: Optional[datetime] = None
    
    # Behavioral metrics
    subscriber_lifetime_value: Optional[float] = None
    subscriber_total_messages: Optional[int] = None
    subscriber_total_purchases: Optional[int] = None
    subscriber_average_response_time: Optional[float] = None
    
    # Conversation flow
    total_exchanges: int = 0
    conversation_duration_minutes: Optional[float] = None
    stages_completed: List[ConversationStage] = []
    
    # Creator metadata
    creator_id: str
    platform: str = "fansly"  # or "onlyfans"


class ConversationDataset(BaseModel):
    """Collection of labeled conversations for training"""
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.now)
    total_conversations: int = 0
    conversations: List[Conversation] = []
    
    # Dataset statistics
    conversion_rate: Optional[float] = None
    average_purchase_amount: Optional[float] = None
    personality_distribution: dict = {}


# Example usage
if __name__ == "__main__":
    # Example conversation
    example = Conversation(
        conversation_id="conv_001",
        subscriber_id="sub_12345",
        creator_id="creator_sunny_charm",
        platform="fansly",
        personality_type=PersonalityType.INSTANT_BUYER,
        outcome_purchased=True,
        purchase_amount=45.0,
        messages=[
            Message(
                timestamp=datetime.now(),
                sender="subscriber",
                content="Hey! Love your content 😍",
                sentiment=SentimentLabel.VERY_POSITIVE,
                purchase_intent_score=7,
                stage=ConversationStage.RAPPORT,
                message_length=25,
                contains_emoji=True
            ),
            Message(
                timestamp=datetime.now(),
                sender="creator",
                content="Aww thank you babe! 💕 What's your favorite kind of content?",
                sentiment=SentimentLabel.POSITIVE,
                stage=ConversationStage.TEASE,
                message_length=55,
                contains_emoji=True
            ),
            # ... more messages
        ],
        total_exchanges=12,
        conversation_duration_minutes=18.5,
        stages_completed=[
            ConversationStage.RAPPORT,
            ConversationStage.TEASE,
            ConversationStage.OFFER,
            ConversationStage.HANDLE,
            ConversationStage.CLOSE
        ]
    )
    
    # Save to JSON
    with open("example_conversation.json", "w") as f:
        f.write(example.model_dump_json(indent=2))
    
    print("✅ Example conversation schema created!")
    print(f"Conversation ID: {example.conversation_id}")
    print(f"Outcome: {'✅ PURCHASED' if example.outcome_purchased else '❌ NO SALE'}")
    print(f"Stages: {' → '.join(s.value for s in example.stages_completed)}")
