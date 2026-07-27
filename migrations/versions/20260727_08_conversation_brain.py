"""Add durable conversation-brain decision records.

Revision ID: 20260727_08
Revises: 20260727_07
"""

import sqlalchemy as sa
from alembic import op


revision = "20260727_08"
down_revision = "20260727_07"
branch_labels = None
depends_on = None

ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "conversation_decisions",
        sa.Column("id", ID_TYPE, autoincrement=True, nullable=False),
        sa.Column("inbound_message_id", ID_TYPE, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_kind", sa.String(length=32), nullable=False),
        sa.Column("fan_state", sa.String(length=64), nullable=False),
        sa.Column("state_summary", sa.Text(), nullable=False),
        sa.Column("objective", sa.String(length=64), nullable=False),
        sa.Column("tactic", sa.String(length=64), nullable=False),
        sa.Column("open_thread", sa.Text(), nullable=True),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("critique", sa.JSON(), nullable=False),
        sa.Column("final_message", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_conversation_decisions_creator_id_creators",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["inbound_messages.id"],
            name=(
                "fk_conversation_decisions_inbound_message_id_"
                "inbound_messages"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_decisions"),
        sa.UniqueConstraint(
            "inbound_message_id",
            name="uq_conversation_decision_inbound",
        ),
    )
    op.create_index(
        "ix_conversation_decision_fan_time",
        "conversation_decisions",
        ["creator_id", "fan_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_decision_fan_time",
        table_name="conversation_decisions",
    )
    op.drop_table("conversation_decisions")
