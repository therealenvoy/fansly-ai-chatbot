"""Add governed Conversation Intelligence corpus releases.

Revision ID: 20260802_29
Revises: 20260802_28
"""

import sqlalchemy as sa
from alembic import op


revision = "20260802_29"
down_revision = "20260802_28"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "conversation_corpus_releases",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("release_key", sa.String(length=96), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("manifest_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("runtime_manifest", sa.JSON(), nullable=False),
        sa.Column("validation_report", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "release_key",
            "version",
            name="uq_conversation_corpus_release_version",
        ),
    )
    op.create_index(
        "ix_conversation_corpus_release_active",
        "conversation_corpus_releases",
        ["creator_id", "status", "release_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_corpus_release_active",
        table_name="conversation_corpus_releases",
    )
    op.drop_table("conversation_corpus_releases")
