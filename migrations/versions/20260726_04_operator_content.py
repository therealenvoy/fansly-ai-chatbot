"""Add durable operator-managed scripts and media registry.

Revision ID: 20260726_04
Revises: 20260726_03
"""

import sqlalchemy as sa
from alembic import op


revision = "20260726_04"
down_revision = "20260726_03"
branch_labels = None
depends_on = None

ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "script_templates",
        sa.Column("id", ID_TYPE, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "messages",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "variables",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "conditions",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
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
            name="fk_script_templates_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_script_templates"),
        sa.UniqueConstraint(
            "creator_id",
            "name",
            name="uq_script_template_creator_name",
        ),
    )
    op.create_index(
        "ix_script_template_category",
        "script_templates",
        ["creator_id", "category"],
        unique=False,
    )

    op.create_table(
        "media_assets",
        sa.Column("id", ID_TYPE, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_media_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("account_media_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column(
            "media_type",
            sa.String(length=32),
            nullable=False,
            server_default="video",
        ),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
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
            name="fk_media_assets_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
        sa.UniqueConstraint(
            "creator_id",
            "provider_media_id",
            name="uq_media_asset_creator_provider_id",
        ),
    )
    op.create_index(
        "ix_media_asset_type",
        "media_assets",
        ["creator_id", "media_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_media_asset_type", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_index(
        "ix_script_template_category",
        table_name="script_templates",
    )
    op.drop_table("script_templates")
