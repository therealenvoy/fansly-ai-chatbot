"""Add versioned prompts, grouped fan turns and human bubble plans.

Revision ID: 20260729_22
Revises: 20260728_21
"""

import sqlalchemy as sa
from alembic import op


revision = "20260729_22"
down_revision = "20260728_21"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("fan_memories_v2") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sensitivity_class",
                sa.String(32),
                nullable=False,
                server_default="standard",
            )
        )
        batch_op.add_column(
            sa.Column(
                "contradiction_status",
                sa.String(32),
                nullable=False,
                server_default="clear",
            )
        )
        batch_op.add_column(sa.Column("source_event_id", sa.String(128)))
    with op.batch_alter_table("fan_conversation_states") as batch_op:
        batch_op.add_column(
            sa.Column(
                "state_evidence",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "trust_estimate",
                sa.Float(),
                nullable=False,
                server_default="0.5",
            )
        )
        batch_op.add_column(
            sa.Column(
                "warmth_estimate",
                sa.Float(),
                nullable=False,
                server_default="0.5",
            )
        )
        batch_op.add_column(
            sa.Column(
                "playfulness_estimate",
                sa.Float(),
                nullable=False,
                server_default="0.5",
            )
        )
        batch_op.add_column(
            sa.Column(
                "question_fatigue",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("pet_name_tolerance", sa.String(32)))
        batch_op.add_column(sa.Column("emoji_preference", sa.String(32)))
        batch_op.add_column(
            sa.Column(
                "conversation_depth",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "state_confidence",
                sa.Float(),
                nullable=False,
                server_default="0.5",
            )
        )

    op.create_table(
        "conversation_documents",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("conflict_findings", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "document_type",
            "revision",
            name="uq_conversation_document_revision",
        ),
    )
    op.create_index(
        "ix_conversation_document_status",
        "conversation_documents",
        ["creator_id", "document_type", "status"],
    )
    op.create_table(
        "conversation_document_events",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("document_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["conversation_documents.id"],
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "conversation_examples",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("fan_tone", sa.String(64), nullable=False),
        sa.Column("relationship_depth", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("intended_act", sa.String(64), nullable=False),
        sa.Column("good_response", sa.Text(), nullable=False),
        sa.Column("anti_example", sa.Text()),
        sa.Column("explanation", sa.Text()),
        sa.Column("safety_class", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_example_selection",
        "conversation_examples",
        ["creator_id", "status", "language", "intended_act"],
    )
    op.create_table(
        "fan_turns",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("chat_id", sa.String(128), nullable=False),
        sa.Column("turn_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("quiet_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "turn_key",
            name="uq_fan_turn_key",
        ),
    )
    op.create_index(
        "ix_fan_turn_ready",
        "fan_turns",
        ["creator_id", "status", "quiet_until"],
    )
    op.create_table(
        "fan_turn_inbound_links",
        sa.Column("turn_id", ID, nullable=False),
        sa.Column("inbound_message_id", ID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["fan_turns.id"]),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["inbound_messages.id"],
        ),
        sa.PrimaryKeyConstraint("turn_id", "inbound_message_id"),
        sa.UniqueConstraint(
            "inbound_message_id",
            name="uq_fan_turn_inbound",
        ),
        sa.UniqueConstraint(
            "turn_id",
            "position",
            name="uq_fan_turn_position",
        ),
    )
    op.create_table(
        "creator_facts",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fact_key", sa.String(128), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("source_document_id", ID),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["conversation_documents.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "creator_id",
            "fact_key",
            "fact_value",
            name="uq_creator_fact_value",
        ),
    )
    op.create_index(
        "ix_creator_fact_active",
        "creator_facts",
        ["creator_id", "status", "fact_key"],
    )
    op.create_table(
        "fan_style_profiles",
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("creator_id", "fan_id"),
    )
    op.create_table(
        "human_response_plans",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("turn_id", ID, nullable=False),
        sa.Column("creator_id", sa.String(64), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("current_decision_id", ID),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("planner_version", sa.String(64), nullable=False),
        sa.Column("prompt_fingerprint", sa.String(64), nullable=False),
        sa.Column("decision_fingerprint", sa.String(64), nullable=False),
        sa.Column("understanding", sa.JSON(), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("delivery", sa.JSON(), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("compilation_report", sa.JSON(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cancel_reason", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["turn_id"], ["fan_turns.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(
            ["current_decision_id"],
            ["conversation_decisions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("turn_id"),
    )
    op.create_index(
        "ix_human_response_plan_status",
        "human_response_plans",
        ["creator_id", "status", "created_at"],
    )
    op.create_table(
        "human_response_bubbles",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("plan_id", ID, nullable=False),
        sa.Column("bubble_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("provider_message_id", sa.String(128)),
        sa.Column("cancellation_reason", sa.String(128)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["human_response_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint(
            "plan_id",
            "bubble_index",
            name="uq_human_response_bubble_position",
        ),
    )
    op.create_index(
        "ix_human_response_bubble_due",
        "human_response_bubbles",
        ["status", "available_at"],
    )
    op.create_table(
        "human_delivery_reviews",
        sa.Column("id", ID, autoincrement=True, nullable=False),
        sa.Column("plan_id", ID, nullable=False),
        sa.Column("reviewer", sa.String(64), nullable=False),
        sa.Column("left_source", sa.String(16), nullable=False),
        sa.Column("right_source", sa.String(16), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("winner", sa.String(16), nullable=False),
        sa.Column("hard_failures", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["human_response_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "reviewer",
            name="uq_human_delivery_review_reviewer",
        ),
    )


def downgrade() -> None:
    op.drop_table("human_delivery_reviews")
    op.drop_index(
        "ix_human_response_bubble_due",
        table_name="human_response_bubbles",
    )
    op.drop_table("human_response_bubbles")
    op.drop_index(
        "ix_human_response_plan_status",
        table_name="human_response_plans",
    )
    op.drop_table("human_response_plans")
    op.drop_table("fan_style_profiles")
    op.drop_index("ix_creator_fact_active", table_name="creator_facts")
    op.drop_table("creator_facts")
    op.drop_table("fan_turn_inbound_links")
    op.drop_index("ix_fan_turn_ready", table_name="fan_turns")
    op.drop_table("fan_turns")
    op.drop_index(
        "ix_conversation_example_selection",
        table_name="conversation_examples",
    )
    op.drop_table("conversation_examples")
    op.drop_table("conversation_document_events")
    op.drop_index(
        "ix_conversation_document_status",
        table_name="conversation_documents",
    )
    op.drop_table("conversation_documents")
    with op.batch_alter_table("fan_conversation_states") as batch_op:
        batch_op.drop_column("state_confidence")
        batch_op.drop_column("conversation_depth")
        batch_op.drop_column("emoji_preference")
        batch_op.drop_column("pet_name_tolerance")
        batch_op.drop_column("question_fatigue")
        batch_op.drop_column("playfulness_estimate")
        batch_op.drop_column("warmth_estimate")
        batch_op.drop_column("trust_estimate")
        batch_op.drop_column("state_evidence")
    with op.batch_alter_table("fan_memories_v2") as batch_op:
        batch_op.drop_column("source_event_id")
        batch_op.drop_column("contradiction_status")
        batch_op.drop_column("sensitivity_class")
