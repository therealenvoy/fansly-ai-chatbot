"""Add provider connection health and sanitized alerts.

Revision ID: 20260728_19
Revises: 20260728_18
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_19"
down_revision = "20260728_18"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "provider_connection_states",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("connection_status", sa.String(32), nullable=False),
        sa.Column(
            "last_connected_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "last_auth_failed_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "provider"),
    )
    op.create_table(
        "provider_alerts",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "event_key",
            name="uq_provider_alert_event",
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_alerts")
    op.drop_table("provider_connection_states")
