from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src.memory.store import MessageStore
from src.persistence.database import create_database_engine
from src.persistence.schema import (
    CONVERSATIONS,
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROVIDER_MESSAGE_STATES,
    PROVIDER_WEBHOOK_EVENTS,
    metadata,
)
from src.persistence.state import ConversationStateRepository
from src.webhooks.onlyfansapi import (
    InvalidWebhookEvent,
    OnlyFansApiFanslyDeletedMessage,
    OnlyFansApiFanslyMessage,
    OnlyFansApiFanslyReadReceipt,
    OnlyFansApiFanslySentMessage,
)
from src.webhooks.repository import WebhookEventRepository


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    return engine


def _event():
    return OnlyFansApiFanslyMessage.from_payload(
        {
            "event": "fansly.messages.received",
            "event_id": "event-a",
            "version": "1",
            "account_id": "account-a",
            "payload": {
                "id": "message-a",
                "groupId": "chat-a",
                "senderId": "fan-a",
                "content": "hello",
                "createdAt": "2026-07-28T00:00:00Z",
            },
        },
        expected_account_id="account-a",
        creator_fansly_id="creator-a-provider-id",
    )


def _sent_event(
    *,
    message_id="creator-message-a",
    created_at="2026-07-28T00:01:00Z",
):
    return OnlyFansApiFanslySentMessage.from_payload(
        {
            "event": "fansly.messages.sent",
            "event_id": f"sent-{message_id}",
            "version": "1",
            "account_id": "account-a",
            "payload": {
                "id": message_id,
                "groupId": "chat-a",
                "senderId": "creator-a-provider-id",
                "recipientId": "fan-a",
                "content": "creator reply",
                "createdAt": created_at,
            },
        },
        expected_account_id="account-a",
        creator_fansly_id="creator-a-provider-id",
    )


def _deleted_event(
    *,
    message_id="message-a",
    created_at="2026-07-28T00:02:00Z",
):
    return OnlyFansApiFanslyDeletedMessage.from_payload(
        {
            "event": "fansly.messages.deleted",
            "event_id": f"deleted-{message_id}",
            "account_id": "account-a",
            "payload": {
                "id": message_id,
                "groupId": "chat-a",
                "fanId": "fan-a",
                "createdAt": created_at,
            },
        },
        expected_account_id="account-a",
    )


def _read_event():
    return OnlyFansApiFanslyReadReceipt.from_payload(
        {
            "event": "fansly.messages.read",
            "event_id": "read-a",
            "account_id": "account-a",
            "payload": {
                "messageIds": ["creator-message-a"],
                "groupId": "chat-a",
                "fanId": "fan-a",
                "createdAt": "2026-07-28T00:03:00Z",
            },
        },
        expected_account_id="account-a",
    )


def test_received_event_commits_ledger_history_and_inbound_once():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    event = _event()

    first = repository.ingest_received(
        creator_id="creator-a",
        event=event,
        available_at=datetime.now(timezone.utc),
    )
    duplicate = repository.ingest_received(
        creator_id="creator-a",
        event=event,
        available_at=datetime.now(timezone.utc),
    )

    assert first.created is True
    assert first.inbound_message_id is not None
    assert duplicate.created is False
    with engine.connect() as connection:
        counts = {
            "events": connection.execute(
                select(func.count(PROVIDER_WEBHOOK_EVENTS.c.id))
            ).scalar_one(),
            "messages": connection.execute(
                select(func.count(FAN_MESSAGES.c.id))
            ).scalar_one(),
            "inbound": connection.execute(
                select(func.count(INBOUND_MESSAGES.c.id))
            ).scalar_one(),
        }
    assert counts == {"events": 1, "messages": 1, "inbound": 1}


def test_missing_provider_timestamp_is_rejected_not_replaced_with_now():
    payload = {
        "event": "fansly.messages.received",
        "account_id": "account-a",
        "payload": {
            "id": "message-a",
            "groupId": "chat-a",
            "senderId": "fan-a",
            "content": "hello",
        },
    }

    with pytest.raises(InvalidWebhookEvent, match="missing provider timestamp"):
        OnlyFansApiFanslyMessage.from_payload(
            payload,
            expected_account_id="account-a",
        )


def test_dead_letter_stores_normalized_metadata_only_and_is_idempotent():
    engine = _engine()
    repository = WebhookEventRepository(engine)

    assert repository.record_dead_letter(
        creator_id="creator-a",
        event_key="a" * 64,
        event_name="fansly.messages.received",
        error_category="invalid_supported_schema",
    )
    assert not repository.record_dead_letter(
        creator_id="creator-a",
        event_key="a" * 64,
        event_name="fansly.messages.received",
        error_category="invalid_supported_schema",
    )
    with engine.connect() as connection:
        row = connection.execute(
            select(PROVIDER_WEBHOOK_EVENTS)
        ).mappings().one()
    assert row["status"] == "dead_letter"
    assert row["platform_message_id"] is None
    assert row["chat_id"] is None


def test_manual_sent_event_cancels_pending_reply_and_never_enqueues_inbound():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    received = repository.ingest_received(
        creator_id="creator-a",
        event=_event(),
        available_at=datetime.now(timezone.utc),
    )
    with engine.begin() as connection:
        connection.execute(
            OUTBOX_MESSAGES.insert().values(
                inbound_message_id=received.inbound_message_id,
                creator_id="creator-a",
                fan_id="fan-a",
                chat_id="chat-a",
                content="stale AI reply",
                message_kind="text",
                media_ids=[],
                status="pending",
                attempt_count=0,
                trigger_source="unread",
                service_role="brain2",
                permit_status="approved",
                contact_policy_version=0,
                created_at=datetime.now(timezone.utc),
            )
        )

    for _ in range(10):
        result = repository.ingest_sent(
            creator_id="creator-a",
            event=_sent_event(),
        )

    assert result.created is False
    with engine.connect() as connection:
        outbox_status = connection.execute(
            select(OUTBOX_MESSAGES.c.status)
        ).scalar_one()
        inbound_rows = connection.execute(
            select(INBOUND_MESSAGES)
        ).mappings().all()
        creator_messages = connection.execute(
            select(FAN_MESSAGES).where(
                FAN_MESSAGES.c.sender == "creator"
            )
        ).mappings().all()
    assert outbox_status == "cancelled_stale"
    assert len(inbound_rows) == 1
    assert inbound_rows[0]["status"] == "completed"
    assert len(creator_messages) == 1
    assert creator_messages[0]["source_class"] == "manual"


def test_out_of_order_sent_and_received_converge_to_newest_speaker():
    for order in ("sent_first", "received_first"):
        engine = _engine()
        repository = WebhookEventRepository(engine)
        received_event = _event()
        sent_event = _sent_event()
        if order == "sent_first":
            repository.ingest_sent(
                creator_id="creator-a",
                event=sent_event,
            )
            repository.ingest_received(
                creator_id="creator-a",
                event=received_event,
                available_at=datetime.now(timezone.utc),
            )
        else:
            repository.ingest_received(
                creator_id="creator-a",
                event=received_event,
                available_at=datetime.now(timezone.utc),
            )
            repository.ingest_sent(
                creator_id="creator-a",
                event=sent_event,
            )
        with engine.connect() as connection:
            conversation = connection.execute(
                select(CONVERSATIONS)
            ).mappings().one()
            inbound_count = connection.execute(
                select(func.count(INBOUND_MESSAGES.c.id))
            ).scalar_one()
        assert conversation["last_speaker"] == "creator"
        assert (
            conversation["last_platform_message_id"]
            == "creator-message-a"
        )
        if order == "sent_first":
            assert inbound_count == 0


def test_delete_before_receive_tombstones_without_creating_work():
    engine = _engine()
    repository = WebhookEventRepository(engine)

    for _ in range(10):
        repository.ingest_deleted(
            creator_id="creator-a",
            event=_deleted_event(
                created_at="2026-07-27T23:59:00Z"
            ),
        )
    received = repository.ingest_received(
        creator_id="creator-a",
        event=_event(),
        available_at=datetime.now(timezone.utc),
    )

    assert received.created is True
    assert received.inbound_message_id is None
    with engine.connect() as connection:
        state = connection.execute(
            select(PROVIDER_MESSAGE_STATES)
        ).mappings().one()
        inbound_count = connection.execute(
            select(func.count(INBOUND_MESSAGES.c.id))
        ).scalar_one()
    assert state["deleted_at"] is not None
    assert inbound_count == 0


def test_deleted_message_is_removed_from_brain_history():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    repository.ingest_received(
        creator_id="creator-a",
        event=_event(),
        available_at=datetime.now(timezone.utc),
    )

    repository.ingest_deleted(
        creator_id="creator-a",
        event=_deleted_event(),
    )

    history = MessageStore(engine=engine).get_history(
        "fan-a",
        "creator-a",
    )
    with engine.connect() as connection:
        row = connection.execute(
            select(FAN_MESSAGES)
        ).mappings().one()
    assert history == []
    assert row["content"] == ""
    assert row["attachments"] == []
    assert row["deleted_at"] is not None


def test_read_receipt_updates_state_without_outbound_or_inbound_work():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    repository.ingest_sent(
        creator_id="creator-a",
        event=_sent_event(),
    )

    for _ in range(10):
        result = repository.ingest_read(
            creator_id="creator-a",
            event=_read_event(),
        )

    assert result.created is False
    with engine.connect() as connection:
        message = connection.execute(
            select(FAN_MESSAGES)
        ).mappings().one()
        inbound_count = connection.execute(
            select(func.count(INBOUND_MESSAGES.c.id))
        ).scalar_one()
        outbox_count = connection.execute(
            select(func.count(OUTBOX_MESSAGES.c.id))
        ).scalar_one()
    assert message["read_at"] is not None
    assert inbound_count == 0
    assert outbox_count == 0
