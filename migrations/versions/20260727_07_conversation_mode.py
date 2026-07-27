"""Add durable conversation triggers and fan presence.

Revision ID: 20260727_07
Revises: 20260726_06
"""

import sqlalchemy as sa
from alembic import op


revision = "20260727_07"
down_revision = "20260726_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "trigger_kind",
                sa.String(length=32),
                nullable=False,
                server_default="unread",
            )
        )
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.alter_column(
            "trigger_kind",
            existing_type=sa.String(length=32),
            server_default=None,
        )

    op.create_table(
        "fan_presence",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_status_id", sa.Integer(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "online_since",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_transition_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_outreach_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
            name="fk_fan_presence_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "fan_id",
            name="pk_fan_presence",
        ),
    )
    op.create_index(
        "ix_fan_presence_status",
        "fan_presence",
        ["creator_id", "status", "last_outreach_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fan_presence_status",
        table_name="fan_presence",
    )
    op.drop_table("fan_presence")
    with op.batch_alter_table("inbound_messages") as batch_op:
        batch_op.drop_column("trigger_kind")
