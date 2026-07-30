"""Add the APIFansly creator connection registry.

Revision ID: 20260730_24
Revises: 20260730_23
"""

import sqlalchemy as sa
from alembic import op


revision = "20260730_24"
down_revision = "20260730_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "creator_connections",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column(
            "provider",
            sa.String(32),
            nullable=False,
            server_default="apifansly",
        ),
        sa.Column("provider_account_id", sa.String(128), nullable=False),
        sa.Column("native_account_id", sa.String(128)),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255)),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("country_code", sa.String(2)),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="connected",
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id"),
        sa.UniqueConstraint(
            "provider_account_id",
            name="uq_creator_connections_provider_account",
        ),
        sa.UniqueConstraint(
            "native_account_id",
            name="uq_creator_connections_native_account",
        ),
    )
    op.create_index(
        "ix_creator_connections_status",
        "creator_connections",
        ["provider", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creator_connections_status",
        table_name="creator_connections",
    )
    op.drop_table("creator_connections")
