"""Add durable Brain 2.0 experiment audit events.

Revision ID: 20260728_12
Revises: 20260728_11
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_12"
down_revision = "20260728_11"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "brain_experiment_events",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("experiment_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["brain_experiments.id"],
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("brain_experiment_events")
