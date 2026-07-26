"""Adopt pre-existing durable tables into Alembic ownership.

Revision ID: 20260726_03
Revises: 20260726_02
"""

import sqlalchemy as sa
from alembic import context, op


revision = "20260726_03"
down_revision = "20260726_02"
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    if context.is_offline_mode():
        return set()
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_fan_notes() -> None:
    op.create_table(
        "fan_notes",
        sa.Column("fan_id", sa.String(), nullable=False),
        sa.Column("creator_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("preferences", sa.Text(), nullable=True),
        sa.Column("occupation", sa.String(), nullable=True),
        sa.Column("total_spent", sa.Float(), nullable=True),
        sa.Column("purchase_count", sa.Integer(), nullable=True),
        sa.Column("last_purchase_at", sa.DateTime(), nullable=True),
        sa.Column("emotional_triggers", sa.Text(), nullable=True),
        sa.Column("hard_limits", sa.Text(), nullable=True),
        sa.Column("facts", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_contact_at", sa.DateTime(), nullable=True),
        sa.Column("relationship_stage", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint(
            "fan_id",
            "creator_id",
            name="pk_fan_notes",
        ),
    )


def _create_fan_messages() -> None:
    op.create_table(
        "fan_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fan_id", sa.String(), nullable=True),
        sa.Column("creator_id", sa.String(), nullable=True),
        sa.Column("sender", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_fan_messages"),
    )
    op.create_index(
        "ix_fan_messages_fan_id",
        "fan_messages",
        ["fan_id"],
        unique=False,
    )
    op.create_index(
        "ix_fan_messages_creator_id",
        "fan_messages",
        ["creator_id"],
        unique=False,
    )


def _create_ppv_sequences() -> None:
    op.create_table(
        "ppv_sequences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("funnel_stage", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ppv_sequences"),
    )


def _create_ppv_sequence_steps() -> None:
    op.create_table(
        "ppv_sequence_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sequence_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.String(), nullable=False),
        sa.Column("preview_id", sa.String(), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("tease_script", sa.Text(), nullable=True),
        sa.Column("offer_script", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ppv_sequence_steps"),
    )


def _create_ppv_fan_progress() -> None:
    op.create_table(
        "ppv_fan_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fan_id", sa.String(), nullable=False),
        sa.Column("sequence_id", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.String(), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("bought_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ppv_fan_progress"),
        sa.UniqueConstraint(
            "fan_id",
            "sequence_id",
            "creator_id",
            name="uq_fan_seq_progress",
        ),
    )


def upgrade() -> None:
    existing = _existing_tables()
    creators = {
        "fan_notes": _create_fan_notes,
        "fan_messages": _create_fan_messages,
        "ppv_sequences": _create_ppv_sequences,
        "ppv_sequence_steps": _create_ppv_sequence_steps,
        "ppv_fan_progress": _create_ppv_fan_progress,
    }
    for table_name, create_table in creators.items():
        if table_name not in existing:
            create_table()

    if (
        not context.is_offline_mode()
        and "fan_notes" in existing
        and "facts"
        not in {
            column["name"]
            for column in sa.inspect(op.get_bind()).get_columns("fan_notes")
        }
    ):
        op.add_column(
            "fan_notes",
            sa.Column(
                "facts",
                sa.Text(),
                nullable=True,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    # These tables may predate Alembic and contain production fan history.
    # Deliberately preserve them instead of performing a destructive downgrade.
    pass
