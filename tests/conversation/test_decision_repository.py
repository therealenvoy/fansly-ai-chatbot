from datetime import datetime, timezone

import pytest

from src.conversation.brain import ConversationDecision
from src.conversation.repository import (
    ConversationDecisionRepository,
    DecisionMetadataValidationError,
)
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import CONVERSATION_DECISIONS, metadata
from src.persistence.state import ConversationStateRepository


def test_decision_repository_upserts_one_audit_record_per_inbound():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    state = ConversationStateRepository(engine)
    state.ensure_conversation("creator-a", "fan-a", "chat-a")
    inbound, _ = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-a",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hello",
        provider_created_at=datetime.now(timezone.utc),
    )
    repository = ConversationDecisionRepository(engine)
    decision = ConversationDecision(
        fan_state="engaged",
        state_summary="Fan asked a direct question.",
        objective="answer",
        tactic="direct_answer",
        open_thread="work",
        draft="draft",
        critique=("specific",),
        final_message="first answer",
        confidence=0.8,
    )

    repository.save(
        inbound_message_id=inbound.id,
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_kind="unread",
        decision=decision,
        model="deepseek-v4-flash",
    )
    repository.save(
        inbound_message_id=inbound.id,
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_kind="unread",
        decision=decision.with_approved_message("approved answer"),
        model="deepseek-v4-flash",
    )

    stored = repository.get(inbound.id, creator_id="creator-a")
    assert stored is not None
    assert stored.decision.objective == "answer"
    assert stored.decision.final_message == "approved answer"
    assert stored.model == "deepseek-v4-flash"


def test_authority_schema_supports_conversation_intelligence_v3():
    authority = CONVERSATION_DECISIONS.c.authority

    assert authority.type.length == 64


def test_decision_repository_rejects_oversized_metadata_before_sql():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    state = ConversationStateRepository(engine)
    state.ensure_conversation("creator-a", "fan-a", "chat-a")
    inbound, _ = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-invalid-metadata",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hello",
        provider_created_at=datetime.now(timezone.utc),
    )
    repository = ConversationDecisionRepository(engine)
    decision = ConversationDecision(
        fan_state="engaged",
        state_summary="Fan asked a direct question.",
        objective="answer",
        tactic="direct_answer",
        open_thread=None,
        draft="draft",
        critique=(),
        final_message="answer",
        confidence=0.8,
    )

    with pytest.raises(DecisionMetadataValidationError) as error:
        repository.save(
            inbound_message_id=inbound.id,
            creator_id="creator-a",
            fan_id="fan-a",
            trigger_kind="unread",
            decision=decision,
            model="deepseek-v4-flash",
            execution={"authority": "x" * 65},
        )

    assert error.value.field == "authority"
    assert error.value.limit == 64
    assert repository.get(inbound.id, creator_id="creator-a") is None
