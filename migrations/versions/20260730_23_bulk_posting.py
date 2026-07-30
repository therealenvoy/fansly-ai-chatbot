"""Add durable bulk-post schedules and provider occurrences.

Revision ID: 20260730_23
Revises: 20260729_22
"""

import sqlalchemy as sa
from alembic import op


revision = "20260730_23"
down_revision = "20260729_22"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "bulk_post_rules",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("wall_ids", sa.JSON(), nullable=False),
        sa.Column("media", sa.JSON(), nullable=False),
        sa.Column("recurrence", sa.String(16), nullable=False),
        sa.Column("carousel", sa.Boolean(), nullable=False),
        sa.Column("paid_preview", sa.Boolean(), nullable=False),
        sa.Column(
            "first_scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "next_scheduled_for",
            sa.DateTime(timezone=True),
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bulk_post_rule_due",
        "bulk_post_rules",
        ["creator_id", "status", "next_scheduled_for"],
    )
    op.create_table(
        "bulk_post_occurrences",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("rule_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column(
            "occurrence_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("provider_post_id", sa.String(128)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_code", sa.String(64)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["bulk_post_rules.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_id",
            "occurrence_index",
            "scheduled_for",
            name="uq_bulk_post_rule_occurrence",
        ),
    )
    op.create_index(
        "ix_bulk_post_occurrence_schedule",
        "bulk_post_occurrences",
        ["creator_id", "scheduled_for", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bulk_post_occurrence_schedule",
        table_name="bulk_post_occurrences",
    )
    op.drop_table("bulk_post_occurrences")
    op.drop_index(
        "ix_bulk_post_rule_due",
        table_name="bulk_post_rules",
    )
    op.drop_table("bulk_post_rules")
