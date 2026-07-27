"""Schedule durable webhook and retry work.

Revision ID: 20260728_09
Revises: 20260727_08
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_09"
down_revision = "20260727_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )

    op.execute(
        sa.text(
            "UPDATE inbound_messages "
            "SET available_at = observed_at "
            "WHERE available_at IS NULL"
        )
    )

    op.drop_index(
        "ix_inbound_pending_order",
        table_name="inbound_messages",
    )
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.alter_column(
            "available_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
    op.create_index(
        "ix_inbound_pending_order",
        "inbound_messages",
        [
            "creator_id",
            "status",
            "available_at",
            "trigger_kind",
            "provider_created_at",
            "id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbound_pending_order",
        table_name="inbound_messages",
    )
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.drop_column("available_at")
    op.create_index(
        "ix_inbound_pending_order",
        "inbound_messages",
        ["creator_id", "status", "provider_created_at", "id"],
        unique=False,
    )
