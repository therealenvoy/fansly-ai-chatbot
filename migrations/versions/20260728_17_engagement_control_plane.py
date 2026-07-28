"""Add native planning, trigger ownership, and contact claims.

Revision ID: 20260728_17
Revises: 20260728_16
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_17"
down_revision = "20260728_16"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "native_automations",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("intended_enabled", sa.Boolean(), nullable=False),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("tier_filters", sa.JSON(), nullable=False),
        sa.Column("tip_keyword", sa.String(128)),
        sa.Column("tip_threshold", sa.Integer()),
        sa.Column("delay_seconds", sa.Integer(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("media_reference", sa.String(128)),
        sa.Column("locked_text", sa.Boolean(), nullable=False),
        sa.Column("configuration_status", sa.String(40), nullable=False),
        sa.Column("provider_automation_id", sa.String(128)),
        sa.Column("operator_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_observed_send_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creator_id", "name", name="uq_native_automation_name"),
    )
    op.create_table(
        "native_campaigns",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("included_tiers", sa.JSON(), nullable=False),
        sa.Column("included_lists", sa.JSON(), nullable=False),
        sa.Column("excluded_lists", sa.JSON(), nullable=False),
        sa.Column("exclude_offline", sa.Boolean(), nullable=False),
        sa.Column("exclude_creators", sa.Boolean(), nullable=False),
        sa.Column("scheduled_time", sa.DateTime(timezone=True)),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("media_metadata", sa.JSON(), nullable=False),
        sa.Column("conversation_only", sa.Boolean(), nullable=False),
        sa.Column("ppv_blocked", sa.Boolean(), nullable=False),
        sa.Column("operator_status", sa.String(40), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creator_id", "name", name="uq_native_campaign_name"),
    )
    op.create_table(
        "trigger_ownership",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("owner", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "trigger_type"),
    )
    op.create_table(
        "trigger_ownership_events",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("previous_owner", sa.String(40)),
        sa.Column("new_owner", sa.String(40), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "contact_claims",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("trigger_event_id", sa.String(128), nullable=False),
        sa.Column("source_system", sa.String(40), nullable=False),
        sa.Column("campaign_or_automation_id", sa.String(128)),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("outbox_id", ID),
        sa.Column("native_message_hash", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("denial_reason", sa.String(128)),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["outbox_id"], ["outbox_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "idempotency_key",
            name="uq_contact_claim_idempotency",
        ),
    )
    op.create_index(
        "ix_contact_claim_fan_time",
        "contact_claims",
        ["creator_id", "fan_id", "claimed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_contact_claim_fan_time", table_name="contact_claims")
    op.drop_table("contact_claims")
    op.drop_table("trigger_ownership_events")
    op.drop_table("trigger_ownership")
    op.drop_table("native_campaigns")
    op.drop_table("native_automations")
