"""Add durable provider history synchronization for the CRM.

Revision ID: 20260726_06
Revises: 20260726_05
"""

import sqlalchemy as sa
from alembic import op


revision = "20260726_06"
down_revision = "20260726_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fans") as batch_op:
        batch_op.add_column(
            sa.Column("username", sa.String(length=255), nullable=True)
        )
        batch_op.add_column(
            sa.Column("avatar_url", sa.Text(), nullable=True)
        )

    with op.batch_alter_table("fan_messages") as batch_op:
        batch_op.add_column(
            sa.Column("chat_id", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("attachments", sa.JSON(), nullable=True)
        )
        batch_op.create_index(
            "ix_fan_messages_creator_message",
            ["creator_id", "message_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_fan_messages_creator_fan_time",
            ["creator_id", "fan_id", "created_at", "id"],
            unique=False,
        )

    op.create_table(
        "crm_chat_sync",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column(
            "provider_head_message_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "stored_head_message_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "incremental_cursor",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "backfill_cursor",
            sa.String(length=512),
            nullable=True,
        ),
        sa.Column(
            "history_complete",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            name="fk_crm_chat_sync_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "chat_id",
            name="pk_crm_chat_sync",
        ),
    )
    op.create_index(
        "ix_crm_chat_sync_pending",
        "crm_chat_sync",
        ["creator_id", "history_complete", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crm_chat_sync_pending",
        table_name="crm_chat_sync",
    )
    op.drop_table("crm_chat_sync")

    with op.batch_alter_table("fan_messages") as batch_op:
        batch_op.drop_index("ix_fan_messages_creator_fan_time")
        batch_op.drop_index("ix_fan_messages_creator_message")
        batch_op.drop_column("attachments")
        batch_op.drop_column("chat_id")

    with op.batch_alter_table("fans") as batch_op:
        batch_op.drop_column("avatar_url")
        batch_op.drop_column("username")
