"""Additive tables for prompt governance, fan turns, and bubble plans."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from src.persistence.schema import metadata, utcnow


ID = BigInteger().with_variant(Integer, "sqlite")

CONVERSATION_DOCUMENTS = Table(
    "conversation_documents",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("document_type", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("status", String(24), nullable=False, default="draft"),
    Column("content", Text, nullable=False),
    Column("document_name", String(256)),
    Column("mime_type", String(128)),
    Column("source_fingerprint", String(64)),
    Column("extraction_status", String(24), nullable=False, default="complete"),
    Column("extraction_report", JSON, nullable=False, default=dict),
    Column("page_count", Integer, nullable=False, default=0),
    Column("character_count", Integer, nullable=False),
    Column("conflict_findings", JSON, nullable=False, default=list),
    Column("source", String(64), nullable=False, default="crm"),
    Column("created_by", String(64), nullable=False, default="operator"),
    Column("activated_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "document_type",
        "revision",
        name="uq_conversation_document_revision",
    ),
)

CONVERSATION_DOCUMENT_EVENTS = Table(
    "conversation_document_events",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column(
        "document_id",
        ID,
        ForeignKey("conversation_documents.id"),
        nullable=False,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("details", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

CONVERSATION_EXAMPLES = Table(
    "conversation_examples",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("stage", String(64), nullable=False),
    Column("fan_tone", String(64), nullable=False),
    Column("relationship_depth", String(64), nullable=False),
    Column("language", String(16), nullable=False, default="en"),
    Column("intended_act", String(64), nullable=False),
    Column("scenario", String(128)),
    Column("conversation_context", Text),
    Column("fan_state", JSON, nullable=False, default=dict),
    Column("good_response", Text, nullable=False),
    Column("anti_example", Text),
    Column("explanation", Text),
    Column(
        "safety_class",
        String(64),
        nullable=False,
        default="conversation_only",
    ),
    Column("status", String(24), nullable=False, default="draft"),
    Column("source_document_id", ID, ForeignKey("conversation_documents.id")),
    Column("source_page", Integer),
    Column("reviewer", String(64)),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("revision", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

FAN_TURNS = Table(
    "fan_turns",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("chat_id", String(128), nullable=False),
    Column("turn_key", String(160), nullable=False),
    Column("status", String(24), nullable=False, default="collecting"),
    Column("quiet_until", DateTime(timezone=True), nullable=False),
    Column("closes_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("last_message_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
    Column("cancel_reason", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "turn_key",
        name="uq_fan_turn_key",
    ),
)

FAN_TURN_INBOUND_LINKS = Table(
    "fan_turn_inbound_links",
    metadata,
    Column("turn_id", ID, ForeignKey("fan_turns.id"), primary_key=True),
    Column(
        "inbound_message_id",
        ID,
        ForeignKey("inbound_messages.id"),
        primary_key=True,
    ),
    Column("position", Integer, nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "inbound_message_id",
        name="uq_fan_turn_inbound",
    ),
    UniqueConstraint(
        "turn_id",
        "position",
        name="uq_fan_turn_position",
    ),
)

CREATOR_FACTS = Table(
    "creator_facts",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fact_key", String(128), nullable=False),
    Column("fact_value", Text, nullable=False),
    Column(
        "source_document_id",
        ID,
        ForeignKey("conversation_documents.id"),
    ),
    Column("confidence", Float, nullable=False, default=1.0),
    Column("status", String(24), nullable=False, default="active"),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_confirmed_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "fact_key",
        "fact_value",
        name="uq_creator_fact_value",
    ),
)

FAN_STYLE_PROFILES = Table(
    "fan_style_profiles",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("fan_id", String(128), primary_key=True),
    Column("metrics", JSON, nullable=False, default=dict),
    Column("sample_count", Integer, nullable=False, default=0),
    Column("profile_version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

HUMAN_RESPONSE_PLANS = Table(
    "human_response_plans",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("turn_id", ID, ForeignKey("fan_turns.id"), nullable=False, unique=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column(
        "current_decision_id",
        ID,
        ForeignKey("conversation_decisions.id"),
    ),
    Column("status", String(24), nullable=False, default="planned"),
    Column("shadow", Boolean, nullable=False, default=True),
    Column("model", String(128), nullable=False),
    Column("planner_version", String(64), nullable=False),
    Column("prompt_fingerprint", String(64), nullable=False),
    Column("decision_fingerprint", String(64), nullable=False),
    Column("understanding", JSON, nullable=False, default=dict),
    Column("strategy", JSON, nullable=False, default=dict),
    Column("delivery", JSON, nullable=False, default=dict),
    Column("quality", JSON, nullable=False, default=dict),
    Column("compilation_report", JSON, nullable=False, default=dict),
    Column("model_calls", Integer, nullable=False, default=0),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("cancel_reason", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

HUMAN_RESPONSE_BUBBLES = Table(
    "human_response_bubbles",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column(
        "plan_id",
        ID,
        ForeignKey("human_response_plans.id"),
        nullable=False,
    ),
    Column("bubble_index", Integer, nullable=False),
    Column("role", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("status", String(24), nullable=False, default="planned"),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("idempotency_key", String(64), nullable=False, unique=True),
    Column("provider_message_id", String(128)),
    Column("cancellation_reason", String(128)),
    Column("sent_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "plan_id",
        "bubble_index",
        name="uq_human_response_bubble_position",
    ),
)

HUMAN_DELIVERY_REVIEWS = Table(
    "human_delivery_reviews",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column(
        "plan_id",
        ID,
        ForeignKey("human_response_plans.id"),
        nullable=False,
    ),
    Column("reviewer", String(64), nullable=False),
    Column("left_source", String(16), nullable=False),
    Column("right_source", String(16), nullable=False),
    Column("scores", JSON, nullable=False),
    Column("winner", String(16), nullable=False),
    Column("hard_failures", JSON, nullable=False, default=list),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "plan_id",
        "reviewer",
        name="uq_human_delivery_review_reviewer",
    ),
)

Index(
    "ix_conversation_document_status",
    CONVERSATION_DOCUMENTS.c.creator_id,
    CONVERSATION_DOCUMENTS.c.document_type,
    CONVERSATION_DOCUMENTS.c.status,
)
Index(
    "ix_conversation_document_fingerprint",
    CONVERSATION_DOCUMENTS.c.creator_id,
    CONVERSATION_DOCUMENTS.c.source_fingerprint,
)
Index(
    "ix_conversation_example_selection",
    CONVERSATION_EXAMPLES.c.creator_id,
    CONVERSATION_EXAMPLES.c.status,
    CONVERSATION_EXAMPLES.c.language,
    CONVERSATION_EXAMPLES.c.intended_act,
)
Index(
    "ix_fan_turn_ready",
    FAN_TURNS.c.creator_id,
    FAN_TURNS.c.status,
    FAN_TURNS.c.quiet_until,
)
Index(
    "ix_creator_fact_active",
    CREATOR_FACTS.c.creator_id,
    CREATOR_FACTS.c.status,
    CREATOR_FACTS.c.fact_key,
)
Index(
    "ix_human_response_plan_status",
    HUMAN_RESPONSE_PLANS.c.creator_id,
    HUMAN_RESPONSE_PLANS.c.status,
    HUMAN_RESPONSE_PLANS.c.created_at,
)
Index(
    "ix_human_response_bubble_due",
    HUMAN_RESPONSE_BUBBLES.c.status,
    HUMAN_RESPONSE_BUBBLES.c.available_at,
)
