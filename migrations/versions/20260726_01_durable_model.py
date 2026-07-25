"""Create the durable fan and message-processing model.

Revision ID: 20260726_01
Revises:
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import context, op


revision = "20260726_01"
down_revision = None
branch_labels = None
depends_on = None

ID_TYPE = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "creators",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_creators"),
    )
    op.create_table(
        "fans",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_fans_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "fan_id",
            name="pk_fans",
        ),
    )
    op.create_table(
        "conversations",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("provider_cursor", sa.String(length=255), nullable=True),
        sa.Column(
            "last_platform_message_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_conversations_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "chat_id",
            name="pk_conversations",
        ),
        sa.UniqueConstraint(
            "creator_id",
            "fan_id",
            name="uq_conversations_creator_fan",
        ),
    )
    op.create_table(
        "fan_runtime_states",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("phase_history", sa.JSON(), nullable=False),
        sa.Column("messages_in_phase", sa.Integer(), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("ppvs_bought", sa.Integer(), nullable=False),
        sa.Column("cooldown", sa.Boolean(), nullable=False),
        sa.Column("consecutive_rejections", sa.Integer(), nullable=False),
        sa.Column("warmup", sa.Boolean(), nullable=False),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("extract_counter", sa.Integer(), nullable=False),
        sa.Column("purchase_count_seen", sa.Integer(), nullable=False),
        sa.Column("rhythm_phase_history", sa.JSON(), nullable=False),
        sa.Column("rhythm_push_count", sa.Integer(), nullable=False),
        sa.Column("rhythm_pull_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_fan_runtime_states_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "fan_id",
            name="pk_fan_runtime_states",
        ),
    )
    op.create_table(
        "creator_settings",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_creator_settings_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "key",
            name="pk_creator_settings",
        ),
    )
    op.create_table(
        "poll_cursors",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_poll_cursors_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "scope",
            name="pk_poll_cursors",
        ),
    )
    op.create_table(
        "processed_platform_messages",
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "platform_message_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_processed_platform_messages_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint(
            "creator_id",
            "platform_message_id",
            name="pk_processed_platform_messages",
        ),
    )
    op.create_table(
        "inbound_messages",
        sa.Column("id", ID_TYPE, autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "platform_message_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "provider_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_inbound_messages_creator_id_creators",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_inbound_messages"),
        sa.UniqueConstraint(
            "creator_id",
            "platform_message_id",
            name="uq_inbound_creator_platform_message",
        ),
    )
    op.create_index(
        "ix_inbound_pending_order",
        "inbound_messages",
        ["creator_id", "status", "provider_created_at", "id"],
        unique=False,
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", ID_TYPE, autoincrement=True, nullable=False),
        sa.Column("inbound_message_id", ID_TYPE, nullable=False),
        sa.Column("creator_id", sa.String(length=64), nullable=False),
        sa.Column("fan_id", sa.String(length=128), nullable=False),
        sa.Column("chat_id", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "provider_message_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_outbox_messages_creator_id_creators",
        ),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["inbound_messages.id"],
            name="fk_outbox_messages_inbound_message_id_inbound_messages",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_messages"),
        sa.UniqueConstraint(
            "creator_id",
            "provider_message_id",
            name="uq_outbox_creator_provider_message",
        ),
        sa.UniqueConstraint(
            "inbound_message_id",
            name="uq_outbox_inbound_message",
        ),
    )
    op.create_index(
        "ix_outbox_pending_order",
        "outbox_messages",
        ["creator_id", "status", "created_at", "id"],
        unique=False,
    )

    bind = op.get_bind()
    if (
        not context.is_offline_mode()
        and "bot_settings" in sa.inspect(bind).get_table_names()
    ):
        legacy_rows = bind.execute(
            sa.text('SELECT "key", "value" FROM bot_settings')
        ).mappings().all()
        if legacy_rows:
            now = datetime.now(timezone.utc)
            creators = sa.table(
                "creators",
                sa.column("id", sa.String()),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            )
            settings = sa.table(
                "creator_settings",
                sa.column("creator_id", sa.String()),
                sa.column("key", sa.String()),
                sa.column("value", sa.Text()),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            )
            op.bulk_insert(
                creators,
                [{"id": "global", "created_at": now, "updated_at": now}],
            )
            op.bulk_insert(
                settings,
                [
                    {
                        "creator_id": "global",
                        "key": row["key"],
                        "value": row["value"],
                        "updated_at": now,
                    }
                    for row in legacy_rows
                ],
            )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_pending_order",
        table_name="outbox_messages",
    )
    op.drop_table("outbox_messages")
    op.drop_index(
        "ix_inbound_pending_order",
        table_name="inbound_messages",
    )
    op.drop_table("inbound_messages")
    op.drop_table("processed_platform_messages")
    op.drop_table("poll_cursors")
    op.drop_table("creator_settings")
    op.drop_table("fan_runtime_states")
    op.drop_table("conversations")
    op.drop_table("fans")
    op.drop_table("creators")
