"""Add typed outbound payloads and purchase ledgers.

Revision ID: 20260726_02
Revises: 20260726_01
"""

import sqlalchemy as sa
from alembic import op


revision = "20260726_02"
down_revision = "20260726_01"
branch_labels = None
depends_on = None

ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.add_column(
        "outbox_messages",
        sa.Column(
            "message_kind",
            sa.String(length=32),
            nullable=False,
            server_default="text",
        ),
    )
    op.add_column(
        "outbox_messages",
        sa.Column(
            "media_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("price_millis", sa.Integer(), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("sequence_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "outbox_messages",
        sa.Column("sequence_step_id", sa.Integer(), nullable=True),
    )

    op.create_table(
        "provider_wallet_transactions",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_transaction_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("transaction_type", sa.Integer(), nullable=False),
        sa.Column("destination", sa.String(length=64), nullable=False),
        sa.Column("amount_millis", sa.BigInteger(), nullable=False),
        sa.Column(
            "destination_tax_millis",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("new_balance_millis", sa.BigInteger(), nullable=False),
        sa.Column(
            "provider_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("provider_status", sa.Integer(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_provider_wallet_transactions_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "provider_transaction_id",
            name="pk_provider_wallet_transactions",
        ),
    )
    op.create_index(
        "ix_wallet_transaction_time",
        "provider_wallet_transactions",
        ["creator_id", "provider_created_at"],
        unique=False,
    )

    op.create_table(
        "purchase_events",
        sa.Column("id", ID_TYPE, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_purchase_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("outbox_message_id", ID_TYPE, nullable=False),
        sa.Column(
            "provider_message_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("amount_millis", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "provider_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_purchase_events_creator_id_creators",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_message_id"],
            ["outbox_messages.id"],
            name="fk_purchase_events_outbox_message_id_outbox_messages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_purchase_events"),
        sa.UniqueConstraint(
            "creator_id",
            "provider_purchase_id",
            name="uq_purchase_creator_provider_purchase",
        ),
    )
    op.create_index(
        "ix_purchase_fan_time",
        "purchase_events",
        ["creator_id", "fan_id", "provider_created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_purchase_fan_time",
        table_name="purchase_events",
    )
    op.drop_table("purchase_events")
    op.drop_index(
        "ix_wallet_transaction_time",
        table_name="provider_wallet_transactions",
    )
    op.drop_table("provider_wallet_transactions")
    op.drop_column("outbox_messages", "sequence_step_id")
    op.drop_column("outbox_messages", "sequence_id")
    op.drop_column("outbox_messages", "price_millis")
    op.drop_column("outbox_messages", "media_ids")
    op.drop_column("outbox_messages", "message_kind")
