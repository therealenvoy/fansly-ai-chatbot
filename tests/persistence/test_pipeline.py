from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql

from src.persistence.database import create_database_engine
from src.persistence.pipeline import (
    INBOUND_COMPLETED,
    INBOUND_FAILED,
    INBOUND_PENDING,
    INBOUND_PROCESSING,
    OUTBOX_DELIVERY_UNKNOWN,
    OUTBOX_PENDING,
    OUTBOX_SENDING,
    OUTBOX_SENT,
    MessageProcessingRepository,
)
from src.persistence.schema import (
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROCESSED_PLATFORM_MESSAGES,
    metadata,
)
from src.persistence.state import ConversationStateRepository


def _repository():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    return engine, MessageProcessingRepository(engine)


def _insert(
    repository,
    message_id,
    created_at,
    *,
    content="hello",
    fan_id="fan-a",
):
    return repository.insert_inbound(
        creator_id="creator-a",
        platform_message_id=message_id,
        fan_id=fan_id,
        chat_id="chat-a",
        content=content,
        provider_created_at=created_at,
    )


def test_inbound_insert_is_idempotent_and_claims_oldest_first():
    _, repository = _repository()
    now = datetime.now(timezone.utc)
    newest, created = _insert(repository, "message-3", now)
    assert created is True
    _insert(repository, "message-1", now - timedelta(minutes=2))
    _insert(repository, "message-2", now - timedelta(minutes=1))

    duplicate, created = _insert(
        repository,
        "message-3",
        now,
        content="changed duplicate",
    )

    assert created is False
    assert duplicate.id == newest.id
    assert duplicate.content == "hello"
    claimed_ids = []
    for _ in range(3):
        claimed = repository.claim_next_inbound("creator-a")
        claimed_ids.append(claimed.platform_message_id)
        repository.complete_without_response(claimed.id)
    assert claimed_ids == ["message-1", "message-2", "message-3"]


def test_postgres_claim_uses_row_lock_and_skip_locked():
    statement = MessageProcessingRepository.inbound_claim_statement(
        "creator-a",
        skip_locked=True,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()

    assert "NOT (EXISTS" in sql
    assert "EARLIER_INBOUND.STATUS IN ('PENDING', 'PROCESSING')" in sql
    assert "ORDER BY INBOUND_MESSAGES.PROVIDER_CREATED_AT ASC" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_newer_inbound_waits_while_oldest_is_processing():
    _, repository = _repository()
    now = datetime.now(timezone.utc)
    _insert(repository, "message-1", now)
    _insert(repository, "message-2", now + timedelta(seconds=1))

    first = repository.claim_next_inbound("creator-a")

    assert first.platform_message_id == "message-1"
    assert repository.claim_next_inbound("creator-a") is None
    repository.complete_without_response(first.id)
    assert (
        repository.claim_next_inbound(
            "creator-a"
        ).platform_message_id
        == "message-2"
    )


def test_allowlist_claim_ignores_older_disallowed_fan():
    _, repository = _repository()
    now = datetime.now(timezone.utc)
    _insert(
        repository,
        "blocked-oldest",
        now,
        fan_id="not-pilot",
    )
    _insert(
        repository,
        "allowed-newer",
        now + timedelta(seconds=1),
        fan_id="pilot",
    )

    claimed = repository.claim_next_inbound(
        "creator-a",
        allowed_fan_ids={"pilot"},
    )

    assert claimed.platform_message_id == "allowed-newer"


def test_empty_allowlist_claims_nothing():
    _, repository = _repository()
    _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )

    assert repository.claim_next_inbound(
        "creator-a",
        allowed_fan_ids=set(),
    ) is None


def test_delivery_lifecycle_records_provider_id_and_processed_marker():
    engine, repository = _repository()
    inbound, _ = _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )
    claimed = repository.claim_next_inbound("creator-a")
    assert claimed.status == INBOUND_PROCESSING
    assert claimed.attempt_count == 1

    outbox, created = repository.enqueue_outbox(
        inbound=claimed,
        content="reply",
    )
    assert created is True
    assert outbox.status == OUTBOX_PENDING

    sending = repository.claim_outbox(outbox.id)
    assert sending.status == OUTBOX_SENDING
    assert sending.attempt_count == 1
    sent, completed = repository.complete_delivery(
        sending.id,
        "provider-reply-1",
    )

    assert sent.status == OUTBOX_SENT
    assert sent.provider_message_id == "provider-reply-1"
    assert completed.status == INBOUND_COMPLETED
    with engine.connect() as conn:
        processed = conn.execute(
            select(PROCESSED_PLATFORM_MESSAGES).where(
                PROCESSED_PLATFORM_MESSAGES.c.platform_message_id
                == inbound.platform_message_id
            )
        ).mappings().one()
    assert processed["fan_id"] == "fan-a"


def test_recovery_requeues_only_work_that_never_started_sending():
    _, repository = _repository()
    _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )
    claimed = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(
        inbound=claimed,
        content="reply",
    )

    recovered = MessageProcessingRepository(
        repository.engine
    ).recover_interrupted("creator-a")

    assert recovered == {
        "requeued": 1,
        "delivery_unknown": 0,
        "completed": 0,
    }
    reclaimed = repository.claim_next_inbound("creator-a")
    assert reclaimed.id == claimed.id
    same_outbox = repository.get_outbox_for_inbound(reclaimed.id)
    assert same_outbox.id == outbox.id
    assert same_outbox.status == OUTBOX_PENDING


def test_recovery_quarantines_an_interrupted_provider_send():
    _, repository = _repository()
    _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )
    inbound = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(
        inbound=inbound,
        content="reply",
    )
    repository.claim_outbox(outbox.id)

    recovered = MessageProcessingRepository(
        repository.engine
    ).recover_interrupted("creator-a")

    assert recovered == {
        "requeued": 0,
        "delivery_unknown": 1,
        "completed": 0,
    }
    quarantined = repository.get_outbox_for_inbound(inbound.id)
    assert quarantined.status == OUTBOX_DELIVERY_UNKNOWN
    assert repository.counts("creator-a") == {
        "inbound_failed": 1,
        "outbox_delivery_unknown": 1,
    }
    assert repository.claim_next_inbound("creator-a") is None
    assert repository.claim_outbox(outbox.id) is None


def test_sent_recovery_restores_completion_and_processed_marker():
    engine, repository = _repository()
    _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )
    inbound = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(
        inbound=inbound,
        content="reply",
    )
    sending = repository.claim_outbox(outbox.id)
    repository.complete_delivery(sending.id, "provider-reply-1")

    with engine.begin() as conn:
        conn.execute(
            update(INBOUND_MESSAGES)
            .where(INBOUND_MESSAGES.c.id == inbound.id)
            .values(
                status=INBOUND_PROCESSING,
                completed_at=None,
            )
        )
        conn.execute(delete(PROCESSED_PLATFORM_MESSAGES))

    recovered = repository.recover_interrupted("creator-a")

    assert recovered["completed"] == 1
    assert repository.counts("creator-a") == {
        "inbound_completed": 1,
        "outbox_sent": 1,
    }
    with engine.connect() as conn:
        assert conn.execute(
            select(PROCESSED_PLATFORM_MESSAGES)
        ).mappings().one()["platform_message_id"] == "message-1"


def test_pre_send_failures_retry_then_quarantine():
    _, repository = _repository()
    _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )

    for attempt in range(1, 4):
        inbound = repository.claim_next_inbound("creator-a")
        assert inbound.attempt_count == attempt
        released = repository.release_inbound(
            inbound.id,
            "generation failed",
            max_attempts=3,
        )
        expected = INBOUND_FAILED if attempt == 3 else INBOUND_PENDING
        assert released.status == expected

    assert repository.claim_next_inbound("creator-a") is None


def test_delivery_unknown_rejects_a_send_that_never_started():
    _, repository = _repository()
    _insert(
        repository,
        "message-1",
        datetime.now(timezone.utc),
    )
    inbound = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(
        inbound=inbound,
        content="reply",
    )

    with pytest.raises(RuntimeError, match="not sending"):
        repository.mark_delivery_unknown(outbox.id, "not attempted")
