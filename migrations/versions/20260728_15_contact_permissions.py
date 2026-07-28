"""Add durable contact policies and expiring send permits.

Revision ID: 20260728_15
Revises: 20260728_14
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_15"
down_revision = "20260728_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fan_contact_policies",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paused_until", sa.DateTime(timezone=True)),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "fan_id"),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("trigger_source", sa.String(32), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("service_role", sa.String(32), nullable=False, server_default="conversation_reply"),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("permit_status", sa.String(32), nullable=False, server_default="unverified"),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("permit_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("contact_policy_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_outbox_permit_status",
        "outbox_messages",
        ["creator_id", "permit_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_permit_status", table_name="outbox_messages")
    op.drop_column("outbox_messages", "contact_policy_version")
    op.drop_column("outbox_messages", "permit_expires_at")
    op.drop_column("outbox_messages", "permit_status")
    op.drop_column("outbox_messages", "service_role")
    op.drop_column("outbox_messages", "trigger_source")
    op.drop_table("fan_contact_policies")
