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
    Column("sender", String),
    Column("content", Text),
    Column("message_id", String, nullable=True),
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
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "creator_id",
        "fan_id",
        name="uq_conversations_creator_fan",
    ),
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
    Column("provider_created_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False, default=utcnow),
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
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("sent_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=True),
    UniqueConstraint("inbound_message_id", name="uq_outbox_inbound_message"),
    UniqueConstraint(
        "creator_id",
        "provider_message_id",
        name="uq_outbox_creator_provider_message",
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

Index(
    "ix_inbound_pending_order",
    INBOUND_MESSAGES.c.creator_id,
    INBOUND_MESSAGES.c.status,
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
