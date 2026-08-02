"""Widen conversation decision authority attribution.

Revision ID: 20260802_30
Revises: 20260802_29
"""

import sqlalchemy as sa
from alembic import op


revision = "20260802_30"
down_revision = "20260802_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_decisions") as batch_op:
        batch_op.alter_column(
            "authority",
            existing_type=sa.String(length=16),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_decisions") as batch_op:
        batch_op.alter_column(
            "authority",
            existing_type=sa.String(length=64),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
