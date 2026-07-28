from datetime import datetime, timezone

from sqlalchemy import select

from src.contact_policy import ContactPolicyRepository, is_opt_out_message
from src.persistence.database import create_database_engine
from src.persistence.pipeline import (
    INBOUND_COMPLETED,
    OUTBOX_BLOCKED_POLICY,
    OUTBOX_BLOCKED_PROVIDER,
    MessageProcessingRepository,
)
from src.persistence.schema import INBOUND_MESSAGES, OUTBOX_MESSAGES, metadata
from src.persistence.state import ConversationStateRepository


def _repository():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    return engine, MessageProcessingRepository(engine)


def _sending(repository):
    inbound, _ = repository.insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-a",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hello",
        provider_created_at=datetime.now(timezone.utc),
    )
    claimed = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(inbound=claimed, content="reply")
    return repository.claim_outbox(outbox.id)


def test_opt_out_phrases_are_conservative():
    assert is_opt_out_message("please stop messaging me")
    assert is_opt_out_message("unsubscribe")
    assert is_opt_out_message("don't contact me")
    assert not is_opt_out_message("stop, that is so funny")


def test_policy_change_revokes_existing_send_permit_at_claim_time():
    engine, repository = _repository()
    inbound, _ = repository.insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-a",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hello",
        provider_created_at=datetime.now(timezone.utc),
    )
    claimed = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(inbound=claimed, content="reply")
    ContactPolicyRepository(engine).record_opt_out("creator-a", "fan-a")

    assert repository.claim_outbox(outbox.id) is None
    with engine.connect() as connection:
        blocked = connection.execute(
            select(OUTBOX_MESSAGES).where(OUTBOX_MESSAGES.c.id == outbox.id)
        ).mappings().one()
        completed = connection.execute(
            select(INBOUND_MESSAGES).where(INBOUND_MESSAGES.c.id == inbound.id)
        ).mappings().one()
    assert blocked["status"] == OUTBOX_BLOCKED_POLICY
    assert blocked["permit_status"] == "revoked"
    assert completed["status"] == INBOUND_COMPLETED


def test_confirmed_provider_rejection_is_not_delivery_unknown():
    engine, repository = _repository()
    sending = _sending(repository)

    blocked = repository.mark_provider_blocked(
        sending.id,
        "PaymentRequiredError",
    )

    assert blocked.status == OUTBOX_BLOCKED_PROVIDER
    assert repository.counts("creator-a") == {
        "inbound_failed": 1,
        "outbox_blocked_provider": 1,
    }
