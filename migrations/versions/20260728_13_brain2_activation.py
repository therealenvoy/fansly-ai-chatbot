"""Add pre-live Brain 2.0 authority telemetry, audit and review storage.

Revision ID: 20260728_13
Revises: 20260728_12
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_13"
down_revision = "20260728_12"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    decision_columns = [
        sa.Column("authority", sa.String(16), nullable=False, server_default="current"),
        sa.Column("brain_version", sa.String(64), nullable=False, server_default="current-v1"),
        sa.Column("route", sa.String(32)),
        sa.Column("experiment_id", sa.String(128)),
        sa.Column("variant", sa.String(64)),
        sa.Column("provider_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repair_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_reason", sa.String(128)),
        sa.Column("gate_results", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("safety_rejection_reason", sa.String(128)),
    ]
    for column in decision_columns:
        op.add_column("conversation_decisions", column)
    op.execute(
        sa.text(
            "UPDATE conversation_decisions SET authority='current', "
            "brain_version='current-v1' WHERE authority IS NULL OR brain_version IS NULL"
        )
    )

    shadow_columns = [
        sa.Column("current_decision_id", ID),
        sa.Column("planned_model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repair_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gate_rejected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_stage", sa.String(32)),
        sa.Column("provider_diagnostic", sa.JSON(), nullable=False, server_default="{}"),
    ]
    for column in shadow_columns:
        op.add_column("brain_shadow_runs", column)
    with op.batch_alter_table("brain_shadow_runs") as batch:
        batch.create_foreign_key(
            "fk_brain_shadow_current_decision",
            "conversation_decisions",
            ["current_decision_id"],
            ["id"],
        )

    op.create_table(
        "brain_cost_buckets",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_cost", sa.Float(), nullable=False),
        sa.Column("limit_snapshot", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "bucket_start"),
    )
    op.create_table(
        "brain_configuration_events",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("previous_values", sa.JSON(), nullable=False),
        sa.Column("new_values", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "brain_comparison_pairs",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("shadow_run_id", ID, nullable=False),
        sa.Column("current_decision_id", ID, nullable=False),
        sa.Column("left_source", sa.String(16), nullable=False),
        sa.Column("right_source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["shadow_run_id"], ["brain_shadow_runs.id"]),
        sa.ForeignKeyConstraint(["current_decision_id"], ["conversation_decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shadow_run_id", name="uq_brain_comparison_shadow_run"),
    )
    op.create_table(
        "brain_blinded_reviews",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("pair_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("reviewer", sa.String(64), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("winner", sa.String(16), nullable=False),
        sa.Column("hard_failures", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pair_id"], ["brain_comparison_pairs.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pair_id", "reviewer", name="uq_brain_blinded_review_reviewer"),
    )


def downgrade() -> None:
    op.drop_table("brain_blinded_reviews")
    op.drop_table("brain_comparison_pairs")
    op.drop_table("brain_configuration_events")
    op.drop_table("brain_cost_buckets")
    with op.batch_alter_table("brain_shadow_runs") as batch:
        batch.drop_constraint(
            "fk_brain_shadow_current_decision",
            type_="foreignkey",
        )
    for name in (
        "provider_diagnostic", "error_stage", "gate_rejected", "fallback_used",
        "estimated_cost", "total_tokens", "completion_tokens", "prompt_tokens",
        "repair_calls", "retry_calls", "provider_attempts", "planned_model_calls",
        "current_decision_id",
    ):
        op.drop_column("brain_shadow_runs", name)
    for name in (
        "safety_rejection_reason", "gate_results", "fallback_reason", "fallback_used",
        "estimated_cost", "latency_ms", "total_tokens", "completion_tokens",
        "prompt_tokens", "repair_calls", "retry_calls", "model_calls",
        "provider_attempts", "variant", "experiment_id", "route", "brain_version",
        "authority",
    ):
        op.drop_column("conversation_decisions", name)
