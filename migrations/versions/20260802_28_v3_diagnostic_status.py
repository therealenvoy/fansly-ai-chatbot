"""Preserve precise Conversation Intelligence V3 outcome codes.

Revision ID: 20260802_28
Revises: 20260801_27
"""

import sqlalchemy as sa
from alembic import op


revision = "20260802_28"
down_revision = "20260801_27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_intelligence_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(24),
            type_=sa.String(64),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_intelligence_runs") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(64),
            type_=sa.String(24),
            existing_nullable=False,
        )
