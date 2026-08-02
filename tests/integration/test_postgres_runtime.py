from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from src.conversation.brain import ConversationDecision
from src.conversation.repository import ConversationDecisionRepository
from src.messaging.models import OutboundMessage
from src.persistence.database import create_database_engine
from src.persistence.migrations import alembic_config, upgrade_database
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.state import ConversationStateRepository


POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="TEST_POSTGRES_URL is required for PostgreSQL integration",
    ),
]


@pytest.fixture(scope="module")
def postgres_engine():
    engine = create_database_engine(
        POSTGRES_URL,
        environment={"APP_ENV": "test"},
    )
    upgrade_database(POSTGRES_URL, engine=engine)
    yield engine
    engine.dispose()


def test_postgres_migrations_and_runtime_tables_initialize(
    postgres_engine,
):
    table_names = set(inspect(postgres_engine).get_table_names())
    assert {
        "alembic_version",
        "creators",
        "fans",
        "conversations",
        "fan_runtime_states",
        "inbound_messages",
        "outbox_messages",
        "purchase_events",
        "provider_wallet_transactions",
        "fan_notes",
        "fan_messages",
        "ppv_sequences",
        "ppv_sequence_steps",
        "ppv_fan_progress",
        "conversation_documents",
        "conversation_document_events",
        "conversation_examples",
        "fan_turns",
        "fan_turn_inbound_links",
        "creator_facts",
        "fan_style_profiles",
        "human_response_plans",
        "human_response_bubbles",
        "human_delivery_reviews",
    } <= table_names
    expected_head = ScriptDirectory.from_config(
        alembic_config(POSTGRES_URL)
    ).get_current_head()
    with postgres_engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == expected_head

    authority_column = next(
        column
        for column in inspect(postgres_engine).get_columns(
            "conversation_decisions"
        )
        if column["name"] == "authority"
    )
    assert authority_column["type"].length == 64


def test_postgres_pipeline_is_idempotent_ordered_and_durable(
    postgres_engine,
):
    suffix = uuid4().hex[:12]
    creator_id = f"ci-{suffix}"
    fan_id = f"fan-{suffix}"
    chat_id = f"chat-{suffix}"
    state = ConversationStateRepository(postgres_engine)
    pipeline = MessageProcessingRepository(postgres_engine)
    state.ensure_creator(creator_id)
    state.ensure_conversation(
        creator_id,
        fan_id,
        chat_id,
        display_name="CI Fan",
    )
    now = datetime.now(timezone.utc)

    newer, newer_created = pipeline.insert_inbound(
        creator_id=creator_id,
        platform_message_id=f"message-newer-{suffix}",
        fan_id=fan_id,
        chat_id=chat_id,
        content="second",
        provider_created_at=now,
    )
    older, older_created = pipeline.insert_inbound(
        creator_id=creator_id,
        platform_message_id=f"message-older-{suffix}",
        fan_id=fan_id,
        chat_id=chat_id,
        content="first",
        provider_created_at=now - timedelta(seconds=10),
    )
    duplicate, duplicate_created = pipeline.insert_inbound(
        creator_id=creator_id,
        platform_message_id=older.platform_message_id,
        fan_id=fan_id,
        chat_id=chat_id,
        content="duplicate",
        provider_created_at=now - timedelta(seconds=10),
    )

    assert newer_created is True
    assert older_created is True
    assert duplicate_created is False
    assert duplicate.id == older.id

    claimed = pipeline.claim_next_inbound(creator_id)
    assert claimed.id == older.id
    outbox, outbox_created = pipeline.enqueue_outbox(
        inbound=claimed,
        message=OutboundMessage.text("approved response"),
    )
    assert outbox_created is True

    sending = pipeline.claim_outbox(outbox.id)
    assert sending is not None
    delivered, completed = pipeline.complete_delivery(
        outbox.id,
        f"provider-message-{suffix}",
    )

    assert delivered.status == "sent"
    assert completed.status == "completed"
    assert state.has_processed(
        creator_id,
        older.platform_message_id,
    )
    assert pipeline.claim_next_inbound(creator_id).id == newer.id


def test_postgres_persists_full_v3_authority_attribution(postgres_engine):
    suffix = uuid4().hex[:12]
    creator_id = f"ci-v3-{suffix}"
    fan_id = f"fan-v3-{suffix}"
    state = ConversationStateRepository(postgres_engine)
    state.ensure_conversation(
        creator_id,
        fan_id,
        f"chat-v3-{suffix}",
    )
    inbound, _ = MessageProcessingRepository(postgres_engine).insert_inbound(
        creator_id=creator_id,
        platform_message_id=f"message-v3-{suffix}",
        fan_id=fan_id,
        chat_id=f"chat-v3-{suffix}",
        content="hello",
        provider_created_at=datetime.now(timezone.utc),
    )
    repository = ConversationDecisionRepository(postgres_engine)
    decision_id = repository.save(
        inbound_message_id=inbound.id,
        creator_id=creator_id,
        fan_id=fan_id,
        trigger_kind="unread",
        decision=ConversationDecision(
            fan_state="engaged",
            state_summary="Fan initiated a conversation.",
            objective="respond",
            tactic="direct_answer",
            open_thread=None,
            draft="hello",
            critique=(),
            final_message="hello",
            confidence=0.8,
        ),
        model="deepseek-v4-flash",
        execution={"authority": "conversation_intelligence_v3"},
    )

    stored = repository.get(inbound.id, creator_id=creator_id)
    assert decision_id > 0
    assert stored is not None
    assert stored.authority == "conversation_intelligence_v3"


def test_postgres_pilot_claim_does_not_wait_on_disallowed_fan(
    postgres_engine,
):
    suffix = uuid4().hex[:12]
    creator_id = f"ci-pilot-{suffix}"
    allowed_fan = f"allowed-{suffix}"
    blocked_fan = f"blocked-{suffix}"
    state = ConversationStateRepository(postgres_engine)
    pipeline = MessageProcessingRepository(postgres_engine)
    state.ensure_creator(creator_id)
    state.ensure_conversation(
        creator_id,
        blocked_fan,
        f"blocked-chat-{suffix}",
    )
    state.ensure_conversation(
        creator_id,
        allowed_fan,
        f"allowed-chat-{suffix}",
    )
    now = datetime.now(timezone.utc)
    pipeline.insert_inbound(
        creator_id=creator_id,
        platform_message_id=f"blocked-message-{suffix}",
        fan_id=blocked_fan,
        chat_id=f"blocked-chat-{suffix}",
        content="older but outside pilot",
        provider_created_at=now,
    )
    allowed, _ = pipeline.insert_inbound(
        creator_id=creator_id,
        platform_message_id=f"allowed-message-{suffix}",
        fan_id=allowed_fan,
        chat_id=f"allowed-chat-{suffix}",
        content="pilot",
        provider_created_at=now + timedelta(seconds=1),
    )

    claimed = pipeline.claim_next_inbound(
        creator_id,
        allowed_fan_ids={allowed_fan},
    )

    assert claimed.id == allowed.id
