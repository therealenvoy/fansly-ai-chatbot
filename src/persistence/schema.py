"""Authoritative durable schema for fan, conversation, and delivery state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
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
