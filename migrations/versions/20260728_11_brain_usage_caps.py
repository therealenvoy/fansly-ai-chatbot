"""Add atomic Brain 2.0 strategic usage caps.

Revision ID: 20260728_11
Revises: 20260728_10
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_11"
down_revision = "20260728_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brain_usage_buckets",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("bucket_kind", sa.String(16), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_calls", sa.Integer(), nullable=False),
        sa.Column("limit_snapshot", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "bucket_kind",
            "bucket_start",
        ),
    )


def downgrade() -> None:
    op.drop_table("brain_usage_buckets")
