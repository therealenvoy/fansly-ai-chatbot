"""Add idempotent fan revenue and lifecycle projections.

Revision ID: 20260728_20
Revises: 20260728_19
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_20"
down_revision = "20260728_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fans") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_follower",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_subscriber",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "subscription_expires_at",
                sa.DateTime(timezone=True),
            )
        )
        batch_op.add_column(
            sa.Column(
                "lifetime_value_minor",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "tip_total_minor",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "purchase_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_revenue_at",
                sa.DateTime(timezone=True),
            )
        )

    op.create_table(
        "fan_revenue_events",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("event_name", sa.String(96), nullable=False),
        sa.Column("provider_event_key", sa.String(64), nullable=False),
        sa.Column("provider_transaction_id", sa.String(128)),
        sa.Column("provider_reference_id", sa.String(128)),
        sa.Column("fan_id", sa.String(128)),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column(
            "ltv_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "tip_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "purchase_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "provider_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "dedupe_key"),
    )


def downgrade() -> None:
    op.drop_table("fan_revenue_events")
    with op.batch_alter_table("fans") as batch_op:
        batch_op.drop_column("last_revenue_at")
        batch_op.drop_column("purchase_count")
        batch_op.drop_column("tip_total_minor")
        batch_op.drop_column("lifetime_value_minor")
        batch_op.drop_column("subscription_expires_at")
        batch_op.drop_column("is_subscriber")
        batch_op.drop_column("is_follower")
