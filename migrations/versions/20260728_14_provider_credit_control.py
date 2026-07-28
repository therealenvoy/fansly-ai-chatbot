"""Add durable provider credit accounting and circuit-breaker state.

Revision ID: 20260728_14
Revises: 20260728_13
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_14"
down_revision = "20260728_13"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "provider_credit_events",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("worker", sa.String(64), nullable=False),
        sa.Column("request_class", sa.String(32), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("status_code", sa.Integer()),
        sa.Column("reserved_credits", sa.Integer(), nullable=False),
        sa.Column("used_credits", sa.Integer()),
        sa.Column("balance", sa.Integer()),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("detail_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_credit_event_time",
        "provider_credit_events",
        ["creator_id", "created_at"],
    )
    op.create_index(
        "ix_provider_credit_event_operation",
        "provider_credit_events",
        ["creator_id", "operation", "result"],
    )
    op.create_table(
        "provider_credit_budgets",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("period_kind", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_class", sa.String(32), nullable=False),
        sa.Column("credit_limit", sa.Integer(), nullable=False),
        sa.Column("used_credits", sa.Integer(), nullable=False),
        sa.Column("reserved_credits", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "provider",
            "period_kind",
            "period_start",
            "request_class",
        ),
    )
    op.create_table(
        "provider_credit_reservations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("worker", sa.String(64), nullable=False),
        sa.Column("request_class", sa.String(32), nullable=False),
        sa.Column("reserved_credits", sa.Integer(), nullable=False),
        sa.Column("used_credits", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_credit_reservation_status",
        "provider_credit_reservations",
        ["creator_id", "status", "created_at"],
    )
    op.create_table(
        "provider_circuit_breakers",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(64)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("operator_reset_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "provider"),
    )


def downgrade() -> None:
    op.drop_table("provider_circuit_breakers")
    op.drop_index(
        "ix_provider_credit_reservation_status",
        table_name="provider_credit_reservations",
    )
    op.drop_table("provider_credit_reservations")
    op.drop_table("provider_credit_budgets")
    op.drop_index(
        "ix_provider_credit_event_operation",
        table_name="provider_credit_events",
    )
    op.drop_index(
        "ix_provider_credit_event_time",
        table_name="provider_credit_events",
    )
    op.drop_table("provider_credit_events")
