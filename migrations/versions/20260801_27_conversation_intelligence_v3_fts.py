"""Add PostgreSQL full-text retrieval index for approved V3 knowledge.

Revision ID: 20260801_27
Revises: 20260801_26
"""

from alembic import op


revision = "20260801_27"
down_revision = "20260801_26"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_conversation_rule_search_fts "
            "ON conversation_knowledge_rules USING GIN "
            "(to_tsvector('simple', coalesce(search_text, '')))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_conversation_rule_search_fts")
