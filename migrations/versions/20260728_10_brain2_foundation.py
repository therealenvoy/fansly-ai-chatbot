"""Add durable Conversation Brain 2.0 foundation.

Revision ID: 20260728_10
Revises: 20260728_09
"""

import sqlalchemy as sa
from alembic import op


revision = "20260728_10"
down_revision = "20260728_09"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "fan_memories_v2",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("memory_type", sa.String(64), nullable=False),
        sa.Column("memory_key", sa.String(128)),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("source_message_id", sa.String(128), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("superseded_by_id", ID),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["fan_memories_v2.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "fan_id",
            "memory_type",
            "normalized_value",
            name="uq_fan_memory_v2_value",
        ),
    )
    op.create_index(
        "ix_fan_memory_v2_retrieval",
        "fan_memories_v2",
        ["creator_id", "fan_id", "status", "importance"],
    )
    op.create_table(
        "conversation_episodes",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("episode_key", sa.String(160), nullable=False),
        sa.Column("main_topics", sa.JSON(), nullable=False),
        sa.Column("emotional_tone", sa.String(64)),
        sa.Column("fan_disclosures", sa.JSON(), nullable=False),
        sa.Column("creator_statements", sa.JSON(), nullable=False),
        sa.Column("boundaries", sa.JSON(), nullable=False),
        sa.Column("resolved_threads", sa.JSON(), nullable=False),
        sa.Column("unresolved_threads", sa.JSON(), nullable=False),
        sa.Column("future_callback", sa.Text()),
        sa.Column("source_start_message_id", sa.String(128), nullable=False),
        sa.Column("source_end_message_id", sa.String(128), nullable=False),
        sa.Column("episode_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("episode_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "fan_id",
            "episode_key",
            name="uq_conversation_episode_key",
        ),
    )
    op.create_index(
        "ix_conversation_episode_fan_time",
        "conversation_episodes",
        ["creator_id", "fan_id", "episode_ended_at"],
    )
    op.create_table(
        "fan_conversation_states",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("relationship_stage", sa.String(64), nullable=False),
        sa.Column("current_mood", sa.String(64), nullable=False),
        sa.Column("current_energy", sa.String(64), nullable=False),
        sa.Column("engagement_estimate", sa.Float(), nullable=False),
        sa.Column("current_objective", sa.String(64)),
        sa.Column("current_tactic", sa.String(64)),
        sa.Column("active_thread", sa.Text()),
        sa.Column("recent_objectives", sa.JSON(), nullable=False),
        sa.Column("recent_tactics", sa.JSON(), nullable=False),
        sa.Column("question_streak", sa.Integer(), nullable=False),
        sa.Column("pet_name_streak", sa.Integer(), nullable=False),
        sa.Column("last_fan_energy", sa.String(64)),
        sa.Column("last_creator_energy", sa.String(64)),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "fan_id"),
    )
    op.create_table(
        "brain_experiments",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("variants", sa.JSON(), nullable=False),
        sa.Column("minimum_sample_size", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creator_id", "name", name="uq_brain_experiment_name"),
    )
    op.create_table(
        "brain_experiment_assignments",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("experiment_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("variant", sa.String(64), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["experiment_id"], ["brain_experiments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id",
            "creator_id",
            "fan_id",
            name="uq_brain_experiment_assignment",
        ),
    )
    op.create_table(
        "brain_shadow_runs",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("inbound_message_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("brain_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("router", sa.JSON(), nullable=False),
        sa.Column("planner", sa.JSON()),
        sa.Column("candidates", sa.JSON()),
        sa.Column("judge", sa.JSON()),
        sa.Column("gate", sa.JSON(), nullable=False),
        sa.Column("selected_candidate", sa.Text()),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "inbound_message_id",
            "brain_version",
            name="uq_brain_shadow_run_version",
        ),
    )
    op.create_index(
        "ix_brain_shadow_run_status",
        "brain_shadow_runs",
        ["creator_id", "status", "created_at"],
    )
    op.create_table(
        "conversation_outcomes",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("conversation_decision_id", ID),
        sa.Column("inbound_message_id", ID, nullable=False),
        sa.Column("outbox_message_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("brain_version", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("experiment_id", sa.String(128)),
        sa.Column("variant", sa.String(64)),
        sa.Column("trigger_kind", sa.String(32), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fan_replied", sa.Boolean(), nullable=False),
        sa.Column("reply_inbound_message_id", sa.BigInteger()),
        sa.Column("reply_latency_seconds", sa.Integer()),
        sa.Column("meaningful_reply", sa.Boolean()),
        sa.Column("continued_three_turns", sa.Boolean(), nullable=False),
        sa.Column("returned_within_24h", sa.Boolean(), nullable=False),
        sa.Column("stalled_recovered", sa.Boolean(), nullable=False),
        sa.Column("negative_signal", sa.Boolean(), nullable=False),
        sa.Column("additional_turns", sa.Integer(), nullable=False),
        sa.Column("attribution_closed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_decision_id"], ["conversation_decisions.id"]
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.ForeignKeyConstraint(["outbox_message_id"], ["outbox_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outbox_message_id"),
    )
    op.create_index(
        "ix_conversation_outcome_fan_sent",
        "conversation_outcomes",
        ["creator_id", "fan_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_outcome_fan_sent",
        table_name="conversation_outcomes",
    )
    op.drop_table("conversation_outcomes")
    op.drop_index("ix_brain_shadow_run_status", table_name="brain_shadow_runs")
    op.drop_table("brain_shadow_runs")
    op.drop_table("brain_experiment_assignments")
    op.drop_table("brain_experiments")
    op.drop_table("fan_conversation_states")
    op.drop_index(
        "ix_conversation_episode_fan_time",
        table_name="conversation_episodes",
    )
    op.drop_table("conversation_episodes")
    op.drop_index("ix_fan_memory_v2_retrieval", table_name="fan_memories_v2")
    op.drop_table("fan_memories_v2")
