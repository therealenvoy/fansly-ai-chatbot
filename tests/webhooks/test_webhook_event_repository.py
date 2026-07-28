from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src.persistence.database import create_database_engine
from src.persistence.schema import (
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    PROVIDER_WEBHOOK_EVENTS,
    metadata,
)
from src.persistence.state import ConversationStateRepository
from src.webhooks.onlyfansapi import (
    InvalidWebhookEvent,
    OnlyFansApiFanslyMessage,
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
