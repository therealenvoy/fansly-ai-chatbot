"""Authoritative durable schema for fan, conversation, and delivery state."""

from __future__ import annotations

from datetime import datetime, timezone

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
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

# Pre-existing durable tables are part of the same Alembic-owned metadata.
FAN_NOTES = Table(
    "fan_notes",
    metadata,
    Column("fan_id", String, primary_key=True),
    Column("creator_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    Column("preferences", Text, default="[]"),
    Column("occupation", String, nullable=True),
    Column("total_spent", Float, default=0.0),
    Column("purchase_count", Integer, default=0),
    Column("last_purchase_at", DateTime, nullable=True),
    Column("emotional_triggers", Text, default="[]"),
    Column("hard_limits", Text, default="[]"),
    Column("facts", Text, default="[]"),
    Column("notes", Text, default=""),
    Column("first_contact_at", DateTime, nullable=True),
    Column("relationship_stage", String, default="new"),
)

FAN_MESSAGES = Table(
    "fan_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fan_id", String, index=True),
    Column("creator_id", String, index=True),
    Column("chat_id", String, nullable=True),
    Column("sender", String),
    Column("content", Text),
    Column("message_id", String, nullable=True),
    Column("attachments", JSON, nullable=True),
    Column("source_class", String(32), nullable=True),
    Column("provider_event_id", String(128), nullable=True),
    Column("read_at", DateTime(timezone=True), nullable=True),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime, default=utcnow),
)

PPV_SEQUENCES = Table(
    "ppv_sequences",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("funnel_stage", String, nullable=False, default="rapport"),
    Column("is_active", Boolean, default=True),
    Column("created_at", DateTime, default=utcnow),
)

PPV_SEQUENCE_STEPS = Table(
    "ppv_sequence_steps",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sequence_id", Integer, nullable=False),
    Column("position", Integer, nullable=False),
    Column("media_id", String, nullable=False),
    Column("preview_id", String, nullable=True),
    Column("price", Float, nullable=False),
    Column("tease_script", Text, default=""),
    Column("offer_script", Text, default=""),
    Column("created_at", DateTime, default=utcnow),
)

PPV_FAN_PROGRESS = Table(
    "ppv_fan_progress",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fan_id", String, nullable=False),
    Column("sequence_id", Integer, nullable=False),
    Column("creator_id", String, nullable=False),
    Column("current_step", Integer, default=0),
    Column("status", String, default="pending"),
    Column("last_sent_at", DateTime, nullable=True),
    Column("bought_at", DateTime, nullable=True),
    Column("started_at", DateTime, default=utcnow),
    UniqueConstraint(
        "fan_id",
        "sequence_id",
        "creator_id",
        name="uq_fan_seq_progress",
    ),
)

CREATORS = Table(
    "creators",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

FANS = Table(
    "fans",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("fan_id", String(128), primary_key=True),
    Column("display_name", String(255), nullable=True),
    Column("username", String(255), nullable=True),
    Column("avatar_url", Text, nullable=True),
    Column("is_follower", Boolean, nullable=False, default=False),
    Column("is_subscriber", Boolean, nullable=False, default=False),
    Column("subscription_expires_at", DateTime(timezone=True), nullable=True),
    Column("lifetime_value_minor", BigInteger, nullable=False, default=0),
    Column("tip_total_minor", BigInteger, nullable=False, default=0),
    Column("purchase_count", Integer, nullable=False, default=0),
    Column("last_revenue_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

FAN_PRESENCE = Table(
    "fan_presence",
    metadata,
    Column(
        "creator_id",
        String(64),
        ForeignKey("creators.id"),
        primary_key=True,
    ),
    Column("fan_id", String(128), primary_key=True),
    Column("status", String(32), nullable=False, default="unknown"),
    Column("provider_status_id", Integer, nullable=True),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("online_since", DateTime(timezone=True), nullable=True),
    Column("last_transition_at", DateTime(timezone=True), nullable=True),
    Column("last_outreach_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

CONVERSATIONS = Table(
    "conversations",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("chat_id", String(128), primary_key=True),
    Column("fan_id", String(128), nullable=False),
    Column("provider_cursor", String(255), nullable=True),
    Column("last_platform_message_id", String(128), nullable=True),
    Column("last_activity_at", DateTime(timezone=True), nullable=True),
    Column("last_speaker", String(16), nullable=True),
    Column("last_fan_message_at", DateTime(timezone=True), nullable=True),
    Column("last_creator_message_at", DateTime(timezone=True), nullable=True),
    Column("last_read_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "fan_id",
        name="uq_conversations_creator_fan",
    ),
)

CRM_CHAT_SYNC = Table(
    "crm_chat_sync",
    metadata,
    Column(
        "creator_id",
        String(64),
        ForeignKey("creators.id"),
        primary_key=True,
    ),
    Column("chat_id", String(128), primary_key=True),
    Column("fan_id", String(128), nullable=False),
    Column("provider_head_message_id", String(128), nullable=True),
    Column("stored_head_message_id", String(128), nullable=True),
    Column("incremental_cursor", String(512), nullable=True),
    Column("backfill_cursor", String(512), nullable=True),
    Column("history_complete", Boolean, nullable=False, default=False),
    Column("last_synced_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

FAN_RUNTIME_STATES = Table(
    "fan_runtime_states",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("fan_id", String(128), primary_key=True),
    Column("phase", String(32), nullable=False, default="rapport"),
    Column("phase_history", JSON, nullable=False, default=lambda: ["rapport"]),
    Column("messages_in_phase", Integer, nullable=False, default=0),
    Column("escalation_level", Integer, nullable=False, default=0),
    Column("ppvs_bought", Integer, nullable=False, default=0),
    Column("cooldown", Boolean, nullable=False, default=False),
    Column("consecutive_rejections", Integer, nullable=False, default=0),
    Column("warmup", Boolean, nullable=False, default=False),
    Column("last_activity_at", DateTime(timezone=True), nullable=True),
    Column("message_count", Integer, nullable=False, default=0),
    Column("extract_counter", Integer, nullable=False, default=0),
    Column("purchase_count_seen", Integer, nullable=False, default=0),
    Column("rhythm_phase_history", JSON, nullable=False, default=lambda: ["pull"]),
    Column("rhythm_push_count", Integer, nullable=False, default=0),
    Column("rhythm_pull_count", Integer, nullable=False, default=0),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

CREATOR_SETTINGS = Table(
    "creator_settings",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

POLL_CURSORS = Table(
    "poll_cursors",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("scope", String(128), primary_key=True),
    Column("cursor", String(512), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

PROCESSED_PLATFORM_MESSAGES = Table(
    "processed_platform_messages",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("platform_message_id", String(128), primary_key=True),
    Column("fan_id", String(128), nullable=False),
    Column("chat_id", String(128), nullable=True),
    Column("processed_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

INBOUND_MESSAGES = Table(
    "inbound_messages",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("platform_message_id", String(128), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("chat_id", String(128), nullable=False),
    Column("content", Text, nullable=False),
    Column("trigger_kind", String(32), nullable=False, default="unread"),
    Column("provider_created_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("available_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("status", String(32), nullable=False, default="pending"),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    UniqueConstraint(
        "creator_id",
        "platform_message_id",
        name="uq_inbound_creator_platform_message",
    ),
)

CONVERSATION_DECISIONS = Table(
    "conversation_decisions",
    metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column(
        "inbound_message_id",
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("inbound_messages.id"),
        nullable=False,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("trigger_kind", String(32), nullable=False),
    Column("fan_state", String(64), nullable=False),
    Column("state_summary", Text, nullable=False),
    Column("objective", String(64), nullable=False),
    Column("tactic", String(64), nullable=False),
    Column("open_thread", Text, nullable=True),
    Column("draft", Text, nullable=False),
    Column("critique", JSON, nullable=False, default=list),
    Column("final_message", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("model", String(128), nullable=False),
    Column("authority", String(16), nullable=False, default="current"),
    Column("brain_version", String(64), nullable=False, default="current-v1"),
    Column("route", String(32)),
    Column("experiment_id", String(128)),
    Column("variant", String(64)),
    Column("provider_attempts", Integer, nullable=False, default=0),
    Column("model_calls", Integer, nullable=False, default=0),
    Column("retry_calls", Integer, nullable=False, default=0),
    Column("repair_calls", Integer, nullable=False, default=0),
    Column("prompt_tokens", Integer, nullable=False, default=0),
    Column("completion_tokens", Integer, nullable=False, default=0),
    Column("total_tokens", Integer, nullable=False, default=0),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("estimated_cost", Float, nullable=False, default=0.0),
    Column("fallback_used", Boolean, nullable=False, default=False),
    Column("fallback_reason", String(128)),
    Column("gate_results", JSON, nullable=False, default=dict),
    Column("safety_rejection_reason", String(128)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "inbound_message_id",
        name="uq_conversation_decision_inbound",
    ),
)

NATIVE_AUTOMATIONS = Table(
    "native_automations", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("name", String(128), nullable=False),
    Column("trigger_type", String(32), nullable=False),
    Column("intended_enabled", Boolean, nullable=False, default=False),
    Column("audience", JSON, nullable=False, default=dict),
    Column("tier_filters", JSON, nullable=False, default=list),
    Column("tip_keyword", String(128)), Column("tip_threshold", Integer),
    Column("delay_seconds", Integer, nullable=False, default=0),
    Column("cooldown_seconds", Integer, nullable=False, default=0),
    Column("message_text", Text, nullable=False),
    Column("message_hash", String(64), nullable=False),
    Column("media_reference", String(128)), Column("locked_text", Boolean, nullable=False, default=False),
    Column("configuration_status", String(40), nullable=False, default="draft"),
    Column("provider_automation_id", String(128)),
    Column("operator_verified_at", DateTime(timezone=True)),
    Column("last_observed_send_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint("creator_id", "name", name="uq_native_automation_name"),
)

NATIVE_CAMPAIGNS = Table(
    "native_campaigns", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("name", String(128), nullable=False), Column("audience", JSON, nullable=False, default=dict),
    Column("included_tiers", JSON, nullable=False, default=list),
    Column("included_lists", JSON, nullable=False, default=list),
    Column("excluded_lists", JSON, nullable=False, default=list),
    Column("exclude_offline", Boolean, nullable=False, default=False),
    Column("exclude_creators", Boolean, nullable=False, default=True),
    Column("scheduled_time", DateTime(timezone=True)),
    Column("cooldown_seconds", Integer, nullable=False, default=0),
    Column("message_text", Text, nullable=False),
    Column("content_fingerprint", String(64), nullable=False),
    Column("media_metadata", JSON, nullable=False, default=dict),
    Column("conversation_only", Boolean, nullable=False, default=True),
    Column("ppv_blocked", Boolean, nullable=False, default=True),
    Column("operator_status", String(40), nullable=False, default="draft"),
    Column("sent_at", DateTime(timezone=True)), Column("observed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint("creator_id", "name", name="uq_native_campaign_name"),
)

TRIGGER_OWNERSHIP = Table(
    "trigger_ownership", metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("trigger_type", String(32), primary_key=True),
    Column("owner", String(40), nullable=False),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_by", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

TRIGGER_OWNERSHIP_EVENTS = Table(
    "trigger_ownership_events", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("trigger_type", String(32), nullable=False),
    Column("previous_owner", String(40)), Column("new_owner", String(40), nullable=False),
    Column("actor", String(64), nullable=False), Column("reason", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

CONTACT_CLAIMS = Table(
    "contact_claims", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("trigger_type", String(32), nullable=False),
    Column("trigger_event_id", String(128), nullable=False),
    Column("source_system", String(40), nullable=False),
    Column("campaign_or_automation_id", String(128)),
    Column("idempotency_key", String(64), nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("cooldown_until", DateTime(timezone=True)),
    Column("outbox_id", BigInteger().with_variant(Integer, "sqlite"), ForeignKey("outbox_messages.id")),
    Column("native_message_hash", String(64)), Column("status", String(32), nullable=False),
    Column("denial_reason", String(128)),
    UniqueConstraint("creator_id", "idempotency_key", name="uq_contact_claim_idempotency"),
)

PROVIDER_WEBHOOK_EVENTS = Table(
    "provider_webhook_events",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("event_key", String(64), nullable=False),
    Column("provider_event_id", String(128), nullable=True),
    Column("event_name", String(96), nullable=False),
    Column("schema_version", String(32), nullable=True),
    Column("platform_message_id", String(128), nullable=True),
    Column("chat_id", String(128), nullable=True),
    Column("direction", String(16), nullable=False),
    Column("source_class", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("error_category", String(64), nullable=True),
    Column("provider_created_at", DateTime(timezone=True), nullable=True),
    Column("received_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("last_received_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("delivery_count", Integer, nullable=False, default=1),
    Column("duplicate_count", Integer, nullable=False, default=0),
    Column("processed_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "creator_id",
        "event_key",
        name="uq_provider_webhook_event_key",
    ),
)

PROVIDER_MESSAGE_STATES = Table(
    "provider_message_states",
    metadata,
    Column(
        "creator_id",
        String(64),
        ForeignKey("creators.id"),
        primary_key=True,
    ),
    Column("platform_message_id", String(128), primary_key=True),
    Column("chat_id", String(128), nullable=True),
    Column("fan_id", String(128), nullable=True),
    Column("direction", String(16), nullable=False, default="unknown"),
    Column("source_class", String(32), nullable=True),
    Column("provider_event_id", String(128), nullable=True),
    Column("provider_created_at", DateTime(timezone=True), nullable=True),
    Column("read_at", DateTime(timezone=True), nullable=True),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)


FAN_CONTACT_POLICIES = Table(
    "fan_contact_policies",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("fan_id", String(128), primary_key=True),
    Column("do_not_contact", Boolean, nullable=False, default=False),
    Column("paused_until", DateTime(timezone=True), nullable=True),
    Column("cooldown_until", DateTime(timezone=True), nullable=True),
    Column("version", Integer, nullable=False, default=1),
    Column("source", String(64), nullable=False),
    Column("reason", String(128), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)


OUTBOX_MESSAGES = Table(
    "outbox_messages",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column(
        "inbound_message_id",
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("inbound_messages.id"),
        nullable=False,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column("chat_id", String(128), nullable=False),
    Column("content", Text, nullable=False),
    Column("message_kind", String(32), nullable=False, default="text"),
    Column("media_ids", JSON, nullable=False, default=list),
    Column("price_millis", Integer, nullable=True),
    Column("sequence_id", Integer, nullable=True),
    Column("sequence_step_id", Integer, nullable=True),
    Column("status", String(32), nullable=False, default="pending"),
    Column("provider_message_id", String(128), nullable=True),
    Column("provider_purchase_ref", String(128), nullable=True),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("sent_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    Column("trigger_source", String(32), nullable=False, default="legacy"),
    Column("service_role", String(32), nullable=False, default="conversation_reply"),
    Column("permit_status", String(32), nullable=False, default="unverified"),
    Column("permit_expires_at", DateTime(timezone=True), nullable=True),
    Column("contact_policy_version", Integer, nullable=False, default=0),
    UniqueConstraint("inbound_message_id", name="uq_outbox_inbound_message"),
    UniqueConstraint(
        "creator_id",
        "provider_message_id",
        name="uq_outbox_creator_provider_message",
    ),
    UniqueConstraint(
        "creator_id",
        "provider_purchase_ref",
        name="uq_outbox_creator_purchase_ref",
    ),
)

PROVIDER_WALLET_TRANSACTIONS = Table(
    "provider_wallet_transactions",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("provider_transaction_id", String(128), primary_key=True),
    Column("transaction_type", Integer, nullable=False),
    Column("destination", String(64), nullable=False),
    Column("amount_millis", BigInteger, nullable=False),
    Column("destination_tax_millis", BigInteger, nullable=False),
    Column("new_balance_millis", BigInteger, nullable=False),
    Column("provider_created_at", DateTime(timezone=True), nullable=False),
    Column("provider_status", Integer, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

PURCHASE_EVENTS = Table(
    "purchase_events",
    metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("provider_purchase_id", String(128), nullable=False),
    Column("fan_id", String(128), nullable=False),
    Column(
        "outbox_message_id",
        BigInteger().with_variant(Integer, "sqlite"),
        ForeignKey("outbox_messages.id"),
        nullable=False,
    ),
    Column("provider_message_id", String(128), nullable=False),
    Column("amount_millis", BigInteger, nullable=False),
    Column("source", String(64), nullable=False),
    Column("provider_created_at", DateTime(timezone=True), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "provider_purchase_id",
        name="uq_purchase_creator_provider_purchase",
    ),
)

SCRIPT_TEMPLATES = Table(
    "script_templates",
    metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("name", String(100), nullable=False),
    Column("category", String(64), nullable=False),
    Column("description", Text, nullable=False, default=""),
    Column("messages", JSON, nullable=False, default=list),
    Column("variables", JSON, nullable=False, default=list),
    Column("conditions", JSON, nullable=False, default=dict),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "name",
        name="uq_script_template_creator_name",
    ),
)

MEDIA_ASSETS = Table(
    "media_assets",
    metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("provider_media_id", String(128), nullable=False),
    Column("account_media_id", String(128), nullable=True),
    Column("title", String(255), nullable=False),
    Column("file_name", String(255), nullable=True),
    Column("media_type", String(32), nullable=False, default="video"),
    Column("mime_type", String(128), nullable=True),
    Column("thumbnail_url", Text, nullable=True),
    Column("preview_url", Text, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("width", Integer, nullable=True),
    Column("height", Integer, nullable=True),
    Column("tags", JSON, nullable=False, default=list),
    Column("source", String(32), nullable=False, default="manual"),
    Column("status", String(32), nullable=False, default="ready"),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "provider_media_id",
        name="uq_media_asset_creator_provider_id",
    ),
)

PROVIDER_CREDIT_EVENTS = Table(
    "provider_credit_events",
    metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("operation", String(64), nullable=False),
    Column("worker", String(64), nullable=False),
    Column("request_class", String(32), nullable=False),
    Column("method", String(8), nullable=False),
    Column("result", String(32), nullable=False),
    Column("status_code", Integer, nullable=True),
    Column("reserved_credits", Integer, nullable=False, default=0),
    Column("used_credits", Integer, nullable=True),
    Column("balance", Integer, nullable=True),
    Column("retry_count", Integer, nullable=False, default=0),
    Column("detail_code", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

PROVIDER_CREDIT_BUDGETS = Table(
    "provider_credit_budgets",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("provider", String(32), primary_key=True),
    Column("period_kind", String(16), primary_key=True),
    Column("period_start", DateTime(timezone=True), primary_key=True),
    Column("request_class", String(32), primary_key=True),
    Column("credit_limit", Integer, nullable=False),
    Column("used_credits", Integer, nullable=False, default=0),
    Column("reserved_credits", Integer, nullable=False, default=0),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

PROVIDER_CREDIT_RESERVATIONS = Table(
    "provider_credit_reservations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("operation", String(64), nullable=False),
    Column("worker", String(64), nullable=False),
    Column("request_class", String(32), nullable=False),
    Column("reserved_credits", Integer, nullable=False),
    Column("used_credits", Integer, nullable=True),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("finalized_at", DateTime(timezone=True), nullable=True),
)

PROVIDER_CIRCUIT_BREAKERS = Table(
    "provider_circuit_breakers",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("provider", String(32), primary_key=True),
    Column("is_open", Boolean, nullable=False, default=False),
    Column("reason_code", String(64), nullable=True),
    Column("opened_at", DateTime(timezone=True), nullable=True),
    Column("operator_reset_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

PROVIDER_CONNECTION_STATES = Table(
    "provider_connection_states",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("provider", String(32), primary_key=True),
    Column("connection_status", String(32), nullable=False),
    Column("last_connected_at", DateTime(timezone=True), nullable=True),
    Column("last_auth_failed_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

PROVIDER_ALERTS = Table(
    "provider_alerts",
    metadata,
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("event_key", String(64), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("code", String(64), nullable=False),
    Column("message", String(255), nullable=False),
    Column("acknowledged_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "event_key",
        name="uq_provider_alert_event",
    ),
)

FAN_REVENUE_EVENTS = Table(
    "fan_revenue_events",
    metadata,
    Column("creator_id", String(64), ForeignKey("creators.id"), primary_key=True),
    Column("dedupe_key", String(64), primary_key=True),
    Column("event_name", String(96), nullable=False),
    Column("provider_event_key", String(64), nullable=False),
    Column("provider_transaction_id", String(128), nullable=True),
    Column("provider_reference_id", String(128), nullable=True),
    Column("fan_id", String(128), nullable=True),
    Column("amount_minor", BigInteger, nullable=False),
    Column("currency", String(8), nullable=False),
    Column("ltv_applied", Boolean, nullable=False, default=False),
    Column("tip_applied", Boolean, nullable=False, default=False),
    Column("purchase_applied", Boolean, nullable=False, default=False),
    Column("provider_created_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

Index(
    "ix_inbound_pending_order",
    INBOUND_MESSAGES.c.creator_id,
    INBOUND_MESSAGES.c.status,
    INBOUND_MESSAGES.c.available_at,
    INBOUND_MESSAGES.c.trigger_kind,
    INBOUND_MESSAGES.c.provider_created_at,
    INBOUND_MESSAGES.c.id,
)
Index(
    "ix_outbox_pending_order",
    OUTBOX_MESSAGES.c.creator_id,
    OUTBOX_MESSAGES.c.status,
    OUTBOX_MESSAGES.c.created_at,
    OUTBOX_MESSAGES.c.id,
)
Index(
    "ix_provider_webhook_event_status",
    PROVIDER_WEBHOOK_EVENTS.c.creator_id,
    PROVIDER_WEBHOOK_EVENTS.c.status,
    PROVIDER_WEBHOOK_EVENTS.c.received_at,
)
Index(
    "ix_provider_webhook_event_message",
    PROVIDER_WEBHOOK_EVENTS.c.creator_id,
    PROVIDER_WEBHOOK_EVENTS.c.platform_message_id,
)
Index(
    "ix_provider_message_state_chat_time",
    PROVIDER_MESSAGE_STATES.c.creator_id,
    PROVIDER_MESSAGE_STATES.c.chat_id,
    PROVIDER_MESSAGE_STATES.c.provider_created_at,
)
Index(
    "ix_outbox_permit_status",
    OUTBOX_MESSAGES.c.creator_id,
    OUTBOX_MESSAGES.c.permit_status,
    OUTBOX_MESSAGES.c.created_at,
)
Index(
    "ix_conversation_decision_fan_time",
    CONVERSATION_DECISIONS.c.creator_id,
    CONVERSATION_DECISIONS.c.fan_id,
    CONVERSATION_DECISIONS.c.created_at,
)
Index(
    "ix_wallet_transaction_time",
    PROVIDER_WALLET_TRANSACTIONS.c.creator_id,
    PROVIDER_WALLET_TRANSACTIONS.c.provider_created_at,
)
Index(
    "ix_purchase_fan_time",
    PURCHASE_EVENTS.c.creator_id,
    PURCHASE_EVENTS.c.fan_id,
    PURCHASE_EVENTS.c.provider_created_at,
)
Index(
    "ix_script_template_category",
    SCRIPT_TEMPLATES.c.creator_id,
    SCRIPT_TEMPLATES.c.category,
)
Index(
    "ix_media_asset_type",
    MEDIA_ASSETS.c.creator_id,
    MEDIA_ASSETS.c.media_type,
    MEDIA_ASSETS.c.created_at,
)
Index(
    "ix_fan_messages_creator_message",
    FAN_MESSAGES.c.creator_id,
    FAN_MESSAGES.c.message_id,
)
Index(
    "ix_fan_messages_creator_fan_time",
    FAN_MESSAGES.c.creator_id,
    FAN_MESSAGES.c.fan_id,
    FAN_MESSAGES.c.created_at,
    FAN_MESSAGES.c.id,
)
Index(
    "ix_crm_chat_sync_pending",
    CRM_CHAT_SYNC.c.creator_id,
    CRM_CHAT_SYNC.c.history_complete,
    CRM_CHAT_SYNC.c.updated_at,
)
Index(
    "ix_fan_presence_status",
    FAN_PRESENCE.c.creator_id,
    FAN_PRESENCE.c.status,
    FAN_PRESENCE.c.last_outreach_at,
)

Index(
    "ix_provider_credit_event_time",
    PROVIDER_CREDIT_EVENTS.c.creator_id,
    PROVIDER_CREDIT_EVENTS.c.created_at,
)
Index(
    "ix_provider_credit_event_operation",
    PROVIDER_CREDIT_EVENTS.c.creator_id,
    PROVIDER_CREDIT_EVENTS.c.operation,
    PROVIDER_CREDIT_EVENTS.c.result,
)
Index(
    "ix_provider_credit_reservation_status",
    PROVIDER_CREDIT_RESERVATIONS.c.creator_id,
    PROVIDER_CREDIT_RESERVATIONS.c.status,
    PROVIDER_CREDIT_RESERVATIONS.c.created_at,
)
Index(
    "ix_contact_claim_fan_time",
    CONTACT_CLAIMS.c.creator_id,
    CONTACT_CLAIMS.c.fan_id,
    CONTACT_CLAIMS.c.claimed_at,
)


# Register additive Brain 2.0 tables in the shared Alembic metadata.
import src.conversation.brain2_schema  # noqa: E402,F401

# Register feature-flagged Human Delivery tables in shared Alembic metadata.
import src.human_delivery.schema  # noqa: E402,F401
