"""Add a normalized durable webhook event ledger.

Revision ID: 20260728_16
Revises: 20260728_15
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_16"
down_revision = "20260728_15"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "provider_webhook_events",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("provider_event_id", sa.String(128)),
        sa.Column("event_name", sa.String(96), nullable=False),
        sa.Column("schema_version", sa.String(32)),
        sa.Column("platform_message_id", sa.String(128)),
        sa.Column("chat_id", sa.String(128)),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("source_class", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_category", sa.String(64)),
        sa.Column("provider_created_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "event_key",
            name="uq_provider_webhook_event_key",
        ),
    )
    op.create_index(
        "ix_provider_webhook_event_status",
        "provider_webhook_events",
        ["creator_id", "status", "received_at"],
    )
    op.create_index(
        "ix_provider_webhook_event_message",
        "provider_webhook_events",
        ["creator_id", "platform_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_webhook_event_message",
        table_name="provider_webhook_events",
    )
    op.drop_index(
        "ix_provider_webhook_event_status",
        table_name="provider_webhook_events",
    )
    op.drop_table("provider_webhook_events")
