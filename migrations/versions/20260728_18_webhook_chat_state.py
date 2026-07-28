"""Add out-of-order-safe webhook chat projections.

Revision ID: 20260728_18
Revises: 20260728_17
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_18"
down_revision = "20260728_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fan_messages") as batch_op:
        batch_op.add_column(
            sa.Column("source_class", sa.String(32))
        )
        batch_op.add_column(
            sa.Column("provider_event_id", sa.String(128))
        )
        batch_op.add_column(
            sa.Column("read_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True))
        )

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(
            sa.Column("last_speaker", sa.String(16))
        )
        batch_op.add_column(
            sa.Column(
                "last_fan_message_at",
                sa.DateTime(timezone=True),
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_creator_message_at",
                sa.DateTime(timezone=True),
            )
        )
        batch_op.add_column(
            sa.Column("last_read_at", sa.DateTime(timezone=True))
        )

    op.create_table(
        "provider_message_states",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column(
            "platform_message_id",
            sa.String(128),
            nullable=False,
        ),
        sa.Column("chat_id", sa.String(128)),
        sa.Column("fan_id", sa.String(128)),
        sa.Column(
            "direction",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("source_class", sa.String(32)),
        sa.Column("provider_event_id", sa.String(128)),
        sa.Column(
            "provider_created_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "platform_message_id",
            name="pk_provider_message_states",
        ),
    )
    op.create_index(
        "ix_provider_message_state_chat_time",
        "provider_message_states",
        ["creator_id", "chat_id", "provider_created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_message_state_chat_time",
        table_name="provider_message_states",
    )
    op.drop_table("provider_message_states")
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("last_read_at")
        batch_op.drop_column("last_creator_message_at")
        batch_op.drop_column("last_fan_message_at")
        batch_op.drop_column("last_speaker")
    with op.batch_alter_table("fan_messages") as batch_op:
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("read_at")
        batch_op.drop_column("provider_event_id")
        batch_op.drop_column("source_class")
