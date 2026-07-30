"""Add creator-scoped durable provider read caching.

Revision ID: 20260730_25
Revises: 20260730_24
"""

import sqlalchemy as sa
from alembic import op


revision = "20260730_25"
down_revision = "20260730_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_read_cache",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "stale_until",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "namespace",
            "cache_key",
        ),
    )
    op.create_index(
        "ix_provider_read_cache_expiry",
        "provider_read_cache",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_read_cache_expiry",
        table_name="provider_read_cache",
    )
    op.drop_table("provider_read_cache")
