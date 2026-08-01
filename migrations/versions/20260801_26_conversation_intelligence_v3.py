"""Add Conversation Intelligence V3 governance and evidence tables.

Revision ID: 20260801_26
Revises: 20260730_25
"""

import sqlalchemy as sa
from alembic import op


revision = "20260801_26"
down_revision = "20260730_25"
branch_labels = None
depends_on = None

ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    with op.batch_alter_table("conversation_documents") as batch_op:
        batch_op.add_column(sa.Column("document_name", sa.String(256)))
        batch_op.add_column(sa.Column("mime_type", sa.String(128)))
        batch_op.add_column(sa.Column("source_fingerprint", sa.String(64)))
        batch_op.add_column(
            sa.Column(
                "extraction_status",
                sa.String(24),
                nullable=False,
                server_default="complete",
            )
        )
        batch_op.add_column(
            sa.Column(
                "extraction_report",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_index(
        "ix_conversation_document_fingerprint",
        "conversation_documents",
        ["creator_id", "source_fingerprint"],
    )

    with op.batch_alter_table("conversation_examples") as batch_op:
        batch_op.add_column(sa.Column("scenario", sa.String(128)))
        batch_op.add_column(sa.Column("conversation_context", sa.Text()))
        batch_op.add_column(
            sa.Column(
                "fan_state",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(sa.Column("source_document_id", ID))
        batch_op.add_column(sa.Column("source_page", sa.Integer()))
        batch_op.add_column(sa.Column("reviewer", sa.String(64)))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True)))
        batch_op.create_foreign_key(
            "fk_conversation_example_source_document",
            "conversation_documents",
            ["source_document_id"],
            ["id"],
        )

    with op.batch_alter_table("fan_conversation_states") as batch_op:
        for name, length in (
            ("current_intent", 96),
            ("underlying_need", 120),
            ("boundary_signal", 128),
            ("last_successful_act", 64),
            ("recommended_next_act", 64),
            ("last_source_message_id", 128),
        ):
            batch_op.add_column(sa.Column(name, sa.String(length)))
        batch_op.add_column(
            sa.Column(
                "current_momentum",
                sa.String(32),
                nullable=False,
                server_default="steady",
            )
        )
        batch_op.add_column(
            sa.Column(
                "intimacy_ceiling",
                sa.String(32),
                nullable=False,
                server_default="neutral",
            )
        )
        for name in (
            "openness_estimate",
            "sexual_intensity",
            "uncertainty_estimate",
            "familiarity_estimate",
            "reciprocity_estimate",
            "emotional_depth",
            "fantasy_openness",
        ):
            batch_op.add_column(
                sa.Column(name, sa.Float(), nullable=False, server_default="0")
            )
        for name in (
            "direct_unanswered_question",
            "unresolved_emotional_thread",
            "creator_promise",
            "fan_promise",
            "future_callback",
        ):
            batch_op.add_column(sa.Column(name, sa.Text()))
        batch_op.add_column(
            sa.Column(
                "recent_failed_acts",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(sa.Column("last_source_timestamp", sa.DateTime(timezone=True)))
    with op.batch_alter_table("conversation_outcomes") as batch_op:
        batch_op.add_column(sa.Column("reply_length", sa.Integer()))
        batch_op.add_column(sa.Column("semantic_substance", sa.Float()))
        batch_op.add_column(sa.Column("emotional_shift", sa.Float()))
        batch_op.add_column(sa.Column("disclosure_depth", sa.Float()))
        for name in (
            "correction_signal",
            "boundary_signal",
            "bot_suspicion",
            "manual_creator_takeover",
        ):
            batch_op.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )
        batch_op.add_column(sa.Column("composite_quality", sa.Float()))

    op.create_table(
        "conversation_document_pages",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("document_id", ID, sa.ForeignKey("conversation_documents.id"), nullable=False),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(256)),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("extraction_quality", sa.Float(), nullable=False, server_default="1"),
        sa.Column("unreadable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "page_number", name="uq_conversation_document_page"),
    )
    op.create_index(
        "ix_conversation_document_page_lookup",
        "conversation_document_pages",
        ["creator_id", "document_id", "page_number"],
    )

    op.create_table(
        "conversation_knowledge_rules",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("rule_key", sa.String(96), nullable=False),
        sa.Column("knowledge_profile", sa.String(32), nullable=False),
        sa.Column("knowledge_type", sa.String(32), nullable=False),
        sa.Column("scenario", sa.String(128), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("relationship_stages", sa.JSON(), nullable=False),
        sa.Column("recommended_acts", sa.JSON(), nullable=False),
        sa.Column("forbidden_acts", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("source_document_id", ID, sa.ForeignKey("conversation_documents.id"), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=False),
        sa.Column("source_excerpt_fingerprint", sa.String(64), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("reviewer", sa.String(64)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("creator_id", "rule_key", "version", name="uq_conversation_rule_version"),
    )
    op.create_index(
        "ix_conversation_rule_retrieval",
        "conversation_knowledge_rules",
        ["creator_id", "status", "knowledge_profile", "scenario", "priority"],
    )

    op.create_table(
        "conversation_knowledge_conflicts",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("left_rule_id", ID, sa.ForeignKey("conversation_knowledge_rules.id"), nullable=False),
        sa.Column("right_rule_id", ID, sa.ForeignKey("conversation_knowledge_rules.id"), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text()),
        sa.Column("reviewer", sa.String(64)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("left_rule_id", "right_rule_id", name="uq_conversation_rule_conflict_pair"),
    )

    op.create_table(
        "fan_state_transitions",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("previous_value", sa.JSON()),
        sa.Column("new_value", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_message_id", sa.String(128), nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_summary", sa.String(240), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "creator_id",
            "fan_id",
            "field_name",
            "source_message_id",
            "state_version",
            name="uq_fan_state_transition_source",
        ),
    )
    op.create_index(
        "ix_fan_state_transition_history",
        "fan_state_transitions",
        ["creator_id", "fan_id", "created_at"],
    )

    op.create_table(
        "fan_callbacks",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("subject_key", sa.String(128), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.String(128), nullable=False),
        sa.Column("first_mentioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("times_referenced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("emotional_sensitivity", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("earliest_safe_reuse_at", sa.DateTime(timezone=True)),
        sa.Column("current_relevance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("creator_id", "fan_id", "subject_key", name="uq_fan_callback_subject"),
    )
    op.create_index(
        "ix_fan_callback_retrieval",
        "fan_callbacks",
        ["creator_id", "fan_id", "resolved", "current_relevance"],
    )

    op.create_table(
        "conversation_intelligence_runs",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("fan_id", sa.String(128), nullable=False),
        sa.Column("inbound_message_id", ID, sa.ForeignKey("inbound_messages.id"), nullable=False),
        sa.Column("current_decision_id", ID, sa.ForeignKey("conversation_decisions.id")),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("shadow", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("versions", sa.JSON(), nullable=False),
        sa.Column("prompt_fingerprint", sa.String(64), nullable=False),
        sa.Column("compilation_report", sa.JSON(), nullable=False),
        sa.Column("understanding", sa.JSON(), nullable=False),
        sa.Column("relationship", sa.JSON(), nullable=False),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("delivery", sa.JSON(), nullable=False),
        sa.Column("candidate_fingerprints", sa.JSON(), nullable=False),
        sa.Column("selected_candidate_fingerprint", sa.String(64)),
        sa.Column("rejection_codes", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("inbound_message_id", "shadow", name="uq_conversation_intelligence_run"),
    )
    op.create_index(
        "ix_conversation_intelligence_run_status",
        "conversation_intelligence_runs",
        ["creator_id", "status", "created_at"],
    )

    op.create_table(
        "conversation_quality_feedback",
        sa.Column("id", ID, primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(64), sa.ForeignKey("creators.id"), nullable=False),
        sa.Column("decision_id", ID, sa.ForeignKey("conversation_decisions.id"), nullable=False),
        sa.Column("intelligence_run_id", ID, sa.ForeignKey("conversation_intelligence_runs.id")),
        sa.Column("outcome_id", ID, sa.ForeignKey("conversation_outcomes.id")),
        sa.Column("feedback_type", sa.String(32), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("playbook_version", sa.String(64)),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("fan_state_fingerprint", sa.String(64)),
        sa.Column("candidate_fingerprint", sa.String(64)),
        sa.Column("edit_distance", sa.Float()),
        sa.Column("reviewer", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversation_quality_feedback",
        "conversation_quality_feedback",
        ["creator_id", "feedback_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_quality_feedback", table_name="conversation_quality_feedback")
    op.drop_table("conversation_quality_feedback")
    op.drop_index("ix_conversation_intelligence_run_status", table_name="conversation_intelligence_runs")
    op.drop_table("conversation_intelligence_runs")
    op.drop_index("ix_fan_callback_retrieval", table_name="fan_callbacks")
    op.drop_table("fan_callbacks")
    op.drop_index("ix_fan_state_transition_history", table_name="fan_state_transitions")
    op.drop_table("fan_state_transitions")
    op.drop_table("conversation_knowledge_conflicts")
    op.drop_index("ix_conversation_rule_retrieval", table_name="conversation_knowledge_rules")
    op.drop_table("conversation_knowledge_rules")
    op.drop_index("ix_conversation_document_page_lookup", table_name="conversation_document_pages")
    op.drop_table("conversation_document_pages")
    with op.batch_alter_table("conversation_outcomes") as batch_op:
        for name in (
            "composite_quality",
            "manual_creator_takeover",
            "bot_suspicion",
            "boundary_signal",
            "correction_signal",
            "disclosure_depth",
            "emotional_shift",
            "semantic_substance",
            "reply_length",
        ):
            batch_op.drop_column(name)
    with op.batch_alter_table("fan_conversation_states") as batch_op:
        for name in (
            "last_source_timestamp",
            "last_source_message_id",
            "recommended_next_act",
            "recent_failed_acts",
            "last_successful_act",
            "future_callback",
            "fan_promise",
            "creator_promise",
            "unresolved_emotional_thread",
            "direct_unanswered_question",
            "intimacy_ceiling",
            "current_momentum",
            "fantasy_openness",
            "emotional_depth",
            "reciprocity_estimate",
            "familiarity_estimate",
            "uncertainty_estimate",
            "sexual_intensity",
            "openness_estimate",
            "boundary_signal",
            "underlying_need",
            "current_intent",
        ):
            batch_op.drop_column(name)
    with op.batch_alter_table("conversation_examples") as batch_op:
        batch_op.drop_constraint("fk_conversation_example_source_document", type_="foreignkey")
        for name in (
            "reviewed_at",
            "reviewer",
            "source_page",
            "source_document_id",
            "fan_state",
            "conversation_context",
            "scenario",
        ):
            batch_op.drop_column(name)
    op.drop_index("ix_conversation_document_fingerprint", table_name="conversation_documents")
    with op.batch_alter_table("conversation_documents") as batch_op:
        for name in (
            "page_count",
            "extraction_report",
            "extraction_status",
            "source_fingerprint",
            "mime_type",
            "document_name",
        ):
            batch_op.drop_column(name)
