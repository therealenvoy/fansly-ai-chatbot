"""Database tables for durable bulk-post schedules."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from ..persistence.schema import metadata, utcnow

ID = BigInteger().with_variant(Integer, "sqlite")

BULK_POST_RULES = Table(
    "bulk_post_rules",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("caption", Text, nullable=False),
    Column("tags", JSON, nullable=False),
    Column("wall_ids", JSON, nullable=False),
    Column("media", JSON, nullable=False),
    Column("recurrence", String(16), nullable=False),
    Column("carousel", Boolean, nullable=False, default=False),
    Column("paid_preview", Boolean, nullable=False, default=False),
    Column("first_scheduled_for", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("next_scheduled_for", DateTime(timezone=True), nullable=True),
    Column("status", String(24), nullable=False),
    Column("last_error_code", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)

BULK_POST_OCCURRENCES = Table(
    "bulk_post_occurrences",
    metadata,
    Column("id", ID, primary_key=True, autoincrement=True),
    Column(
        "rule_id",
        ID,
        ForeignKey("bulk_post_rules.id"),
        nullable=False,
    ),
    Column("creator_id", String(64), ForeignKey("creators.id"), nullable=False),
    Column("occurrence_index", Integer, nullable=False, default=0),
    Column("scheduled_for", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("provider_post_id", String(128), nullable=True),
    Column("status", String(24), nullable=False),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("error_code", String(64), nullable=True),
    Column("submitted_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
    UniqueConstraint(
        "rule_id",
        "occurrence_index",
        "scheduled_for",
        name="uq_bulk_post_rule_occurrence",
    ),
)

Index(
    "ix_bulk_post_rule_due",
    BULK_POST_RULES.c.creator_id,
    BULK_POST_RULES.c.status,
    BULK_POST_RULES.c.next_scheduled_for,
)
Index(
    "ix_bulk_post_occurrence_schedule",
    BULK_POST_OCCURRENCES.c.creator_id,
    BULK_POST_OCCURRENCES.c.scheduled_for,
    BULK_POST_OCCURRENCES.c.status,
)
