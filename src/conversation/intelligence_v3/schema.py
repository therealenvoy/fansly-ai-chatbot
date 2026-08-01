"""Additive durable schema for Conversation Intelligence V3."""

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

CONVERSATION_DOCUMENT_PAGES = Table(
    "conversation_document_pages",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("document_id", ID, ForeignKey("conversation_documents.id"), nullable=False),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("page_number", Integer, nullable=False),
    Column("section", String(256)),
    Column("content", Text, nullable=False),
    Column("content_fingerprint", String(64), nullable=False),
    Column("extraction_quality", Float, nullable=False, default=1.0),
    Column("unreadable", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint("document_id", "page_number", name="uq_conversation_document_page"),
)

CONVERSATION_KNOWLEDGE_RULES = Table(
    "conversation_knowledge_rules",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("rule_key", String(96), nullable=False),
    Column("knowledge_profile", String(32), nullable=False),
    Column("knowledge_type", String(32), nullable=False),
    Column("scenario", String(128), nullable=False),
    Column("conditions", JSON, nullable=False, default=list),
    Column("relationship_stages", JSON, nullable=False, default=list),
    Column("recommended_acts", JSON, nullable=False, default=list),
    Column("forbidden_acts", JSON, nullable=False, default=list),
    Column("priority", Integer, nullable=False, default=50),
    Column("source_document_id", ID, ForeignKey("conversation_documents.id"), nullable=False),
    Column("source_page", Integer, nullable=False),
    Column("source_excerpt_fingerprint", String(64), nullable=False),
    Column("search_text", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(24), nullable=False, default="draft"),
    Column("reviewer", String(64)),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint("creator_id", "rule_key", "version", name="uq_conversation_rule_version"),
)

CONVERSATION_KNOWLEDGE_CONFLICTS = Table(
    "conversation_knowledge_conflicts",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("left_rule_id", ID, ForeignKey("conversation_knowledge_rules.id"), nullable=False),
    Column("right_rule_id", ID, ForeignKey("conversation_knowledge_rules.id"), nullable=False),
    Column("reason_code", String(64), nullable=False),
    Column("status", String(24), nullable=False, default="open"),
    Column("resolution", Text),
    Column("reviewer", String(64)),
    Column("resolved_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint("left_rule_id", "right_rule_id", name="uq_conversation_rule_conflict_pair"),
)

FAN_STATE_TRANSITIONS = Table(
    "fan_state_transitions",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("shadow", Boolean, nullable=False, default=True),
    Column("field_name", String(64), nullable=False),
    Column("previous_value", JSON),
    Column("new_value", JSON, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("source_message_id", String(128), nullable=False),
    Column("source_timestamp", DateTime(timezone=True), nullable=False),
    Column("evidence_summary", String(240), nullable=False),
    Column("reason_code", String(64), nullable=False),
    Column("state_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "fan_id",
        "field_name",
        "source_message_id",
        "state_version",
        name="uq_fan_state_transition_source",
    ),
)

FAN_CALLBACKS = Table(
    "fan_callbacks",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("subject_key", String(128), nullable=False),
    Column("subject", Text, nullable=False),
    Column("source_message_id", String(128), nullable=False),
    Column("first_mentioned_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True)),
    Column("times_referenced", Integer, nullable=False, default=0),
    Column("resolved", Boolean, nullable=False, default=False),
    Column("emotional_sensitivity", String(32), nullable=False, default="standard"),
    Column("earliest_safe_reuse_at", DateTime(timezone=True)),
    Column("current_relevance", Float, nullable=False, default=0.5),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint("creator_id", "fan_id", "subject_key", name="uq_fan_callback_subject"),
)

CONVERSATION_INTELLIGENCE_RUNS = Table(
    "conversation_intelligence_runs",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("inbound_message_id", ID, ForeignKey("inbound_messages.id"), nullable=False),
    Column("current_decision_id", ID, ForeignKey("conversation_decisions.id")),
    Column("status", String(24), nullable=False),
    Column("shadow", Boolean, nullable=False, default=True),
    Column("versions", JSON, nullable=False, default=dict),
    Column("prompt_fingerprint", String(64), nullable=False),
    Column("compilation_report", JSON, nullable=False, default=dict),
    Column("understanding", JSON, nullable=False, default=dict),
    Column("relationship", JSON, nullable=False, default=dict),
    Column("strategy", JSON, nullable=False, default=dict),
    Column("delivery", JSON, nullable=False, default=dict),
    Column("candidate_fingerprints", JSON, nullable=False, default=list),
    Column("selected_candidate_fingerprint", String(64)),
    Column("rejection_codes", JSON, nullable=False, default=list),
    Column("model", String(128), nullable=False),
    Column("model_calls", Integer, nullable=False, default=0),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("estimated_cost", Float, nullable=False, default=0.0),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("completed_at", DateTime(timezone=True)),
    UniqueConstraint("inbound_message_id", "shadow", name="uq_conversation_intelligence_run"),
)

CONVERSATION_QUALITY_FEEDBACK = Table(
    "conversation_quality_feedback",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("decision_id", ID, ForeignKey("conversation_decisions.id"), nullable=False),
    Column("intelligence_run_id", ID, ForeignKey("conversation_intelligence_runs.id")),
    Column("outcome_id", ID, ForeignKey("conversation_outcomes.id")),
    Column("feedback_type", String(32), nullable=False),
    Column("prompt_version", String(64), nullable=False),
    Column("playbook_version", String(64)),
    Column("model", String(128), nullable=False),
    Column("fan_state_fingerprint", String(64)),
    Column("candidate_fingerprint", String(64)),
    Column("edit_distance", Float),
    Column("reviewer", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

Index(
    "ix_conversation_document_page_lookup",
    CONVERSATION_DOCUMENT_PAGES.c.creator_id,
    CONVERSATION_DOCUMENT_PAGES.c.document_id,
    CONVERSATION_DOCUMENT_PAGES.c.page_number,
)
Index(
    "ix_conversation_rule_retrieval",
    CONVERSATION_KNOWLEDGE_RULES.c.creator_id,
    CONVERSATION_KNOWLEDGE_RULES.c.status,
    CONVERSATION_KNOWLEDGE_RULES.c.knowledge_profile,
    CONVERSATION_KNOWLEDGE_RULES.c.scenario,
    CONVERSATION_KNOWLEDGE_RULES.c.priority,
)
Index(
    "ix_fan_state_transition_history",
    FAN_STATE_TRANSITIONS.c.creator_id,
    FAN_STATE_TRANSITIONS.c.fan_id,
    FAN_STATE_TRANSITIONS.c.created_at,
)
Index(
    "ix_fan_callback_retrieval",
    FAN_CALLBACKS.c.creator_id,
    FAN_CALLBACKS.c.fan_id,
    FAN_CALLBACKS.c.resolved,
    FAN_CALLBACKS.c.current_relevance,
)
Index(
    "ix_conversation_intelligence_run_status",
    CONVERSATION_INTELLIGENCE_RUNS.c.creator_id,
    CONVERSATION_INTELLIGENCE_RUNS.c.status,
    CONVERSATION_INTELLIGENCE_RUNS.c.created_at,
)
Index(
    "ix_conversation_quality_feedback",
    CONVERSATION_QUALITY_FEEDBACK.c.creator_id,
    CONVERSATION_QUALITY_FEEDBACK.c.feedback_type,
    CONVERSATION_QUALITY_FEEDBACK.c.created_at,
)
