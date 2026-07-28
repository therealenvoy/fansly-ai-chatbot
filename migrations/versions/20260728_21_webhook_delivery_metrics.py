"""Add durable webhook delivery and duplicate metrics.

Revision ID: 20260728_21
Revises: 20260728_20
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_21"
down_revision = "20260728_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("provider_webhook_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "last_received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "delivery_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "duplicate_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("provider_webhook_events") as batch_op:
        batch_op.drop_column("duplicate_count")
        batch_op.drop_column("delivery_count")
        batch_op.drop_column("last_received_at")
