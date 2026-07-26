"""Persist the provider account-media reference used by PPV webhooks.

Revision ID: 20260726_05
Revises: 20260726_04
"""

import sqlalchemy as sa
from alembic import op


revision = "20260726_05"
down_revision = "20260726_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outbox_messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider_purchase_ref",
                sa.String(length=128),
                nullable=True,
            )
        )
        batch_op.create_unique_constraint(
            "uq_outbox_creator_purchase_ref",
            ["creator_id", "provider_purchase_ref"],
        )


def downgrade() -> None:
    with op.batch_alter_table("outbox_messages") as batch_op:
        batch_op.drop_constraint(
            "uq_outbox_creator_purchase_ref",
            type_="unique",
        )
        batch_op.drop_column("provider_purchase_ref")
