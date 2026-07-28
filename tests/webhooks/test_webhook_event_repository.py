from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src.memory.store import MessageStore
from src.persistence.database import create_database_engine
from src.persistence.schema import (
    CONVERSATIONS,
    CREATOR_SETTINGS,
    FAN_REVENUE_EVENTS,
    FANS,
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROVIDER_ALERTS,
    PROVIDER_CIRCUIT_BREAKERS,
    PROVIDER_CONNECTION_STATES,
    PROVIDER_MESSAGE_STATES,
    PROVIDER_WEBHOOK_EVENTS,
    metadata,
)
from src.persistence.state import ConversationStateRepository
from src.webhooks.onlyfansapi import (
    InvalidWebhookEvent,
    OnlyFansApiFanslyAccountEvent,
    OnlyFansApiFanslyDeletedMessage,
    OnlyFansApiFanslyDomainEvent,
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
    payload_overrides=None,
):
    payload = {
        "id": message_id,
        "groupId": "chat-a",
        "senderId": "creator-a-provider-id",
        "recipientId": "fan-a",
        "content": "creator reply",
        "createdAt": created_at,
    }
    payload.update(payload_overrides or {})
    return OnlyFansApiFanslySentMessage.from_payload(
        {
            "event": "fansly.messages.sent",
            "event_id": f"sent-{message_id}",
            "version": "1",
            "account_id": "account-a",
            "payload": payload,
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


def _account_event(event_name, event_id):
    return OnlyFansApiFanslyAccountEvent.from_payload(
        {
            "event": event_name,
            "event_id": event_id,
            "account_id": "account-a",
            "timestamp": "2026-07-28T00:04:00Z",
        },
        expected_account_id="account-a",
    )


def _domain_event(
    event_name,
    event_id,
    *,
    fan_id="fan-a",
    transaction_id=None,
    reference_id=None,
    amount="12.34",
):
    payload = {
        "id": reference_id or event_id,
        "fanId": fan_id,
        "createdAt": "2026-07-28T00:05:00Z",
    }
    if transaction_id is not None:
        payload["transactionId"] = transaction_id
    if event_name in {
        "fansly.transactions.new",
        "fansly.tips.received",
        "fansly.media.purchased",
        "fansly.stories.purchased",
    }:
        payload["amount"] = amount
        payload["currency"] = "USD"
    if fan_id is None:
        payload.pop("fanId")
    return OnlyFansApiFanslyDomainEvent.from_payload(
        {
            "event": event_name,
            "event_id": event_id,
            "account_id": "account-a",
            "payload": payload,
        },
        expected_account_id="account-a",
    )


def test_received_event_commits_ledger_history_and_inbound_once():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    event = _event()

    results = [
        repository.ingest_received(
            creator_id="creator-a",
            event=event,
            available_at=datetime.now(timezone.utc),
        )
        for _ in range(10)
    ]
    first, *duplicates = results

    assert first.created is True
    assert first.inbound_message_id is not None
    assert all(duplicate.created is False for duplicate in duplicates)
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
            "duplicates": connection.execute(
                select(
                    func.sum(
                        PROVIDER_WEBHOOK_EVENTS.c.duplicate_count
                    )
                )
            ).scalar_one(),
        }
    assert counts == {
        "events": 1,
        "messages": 1,
        "inbound": 1,
        "duplicates": 9,
    }


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


@pytest.mark.parametrize(
    ("payload_overrides", "matched_outbox", "expected"),
    (
        ({}, object(), "ai"),
        ({"automationId": "automation-a"}, None, "native_automation"),
        ({"integrationId": "integration-a"}, None, "external_api"),
        ({}, None, "manual"),
    ),
)
def test_sent_source_class_distinguishes_every_creator_origin(
    payload_overrides,
    matched_outbox,
    expected,
):
    event = _sent_event(payload_overrides=payload_overrides)

    assert (
        WebhookEventRepository._sent_source_class(
            event,
            matched_outbox,
        )
        == expected
    )


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


def test_authentication_failure_opens_circuit_and_disables_bot_atomically():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    event = _account_event(
        "fansly.accounts.authentication_failed",
        "auth-failed-a",
    )

    for _ in range(10):
        result = repository.ingest_account(
            creator_id="creator-a",
            event=event,
        )

    assert result.created is False
    with engine.connect() as connection:
        circuit = connection.execute(
            select(PROVIDER_CIRCUIT_BREAKERS)
        ).mappings().one()
        bot_enabled = connection.execute(
            select(CREATOR_SETTINGS.c.value).where(
                CREATOR_SETTINGS.c.key == "bot_enabled"
            )
        ).scalar_one()
        alerts = connection.execute(
            select(PROVIDER_ALERTS)
        ).mappings().all()
    assert circuit["is_open"] is True
    assert circuit["reason_code"] == "authentication_failed"
    assert bot_enabled == "false"
    assert len(alerts) == 1
    assert "authentication" in alerts[0]["message"].lower()


def test_connected_event_updates_visibility_without_resetting_circuit():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    repository.ingest_account(
        creator_id="creator-a",
        event=_account_event(
            "fansly.accounts.authentication_failed",
            "auth-failed-a",
        ),
    )

    repository.ingest_account(
        creator_id="creator-a",
        event=_account_event(
            "fansly.accounts.connected",
            "connected-a",
        ),
    )

    with engine.connect() as connection:
        state = connection.execute(
            select(PROVIDER_CONNECTION_STATES)
        ).mappings().one()
        circuit_open = connection.execute(
            select(PROVIDER_CIRCUIT_BREAKERS.c.is_open)
        ).scalar_one()
    assert state["connection_status"] == "connected"
    assert state["last_connected_at"] is not None
    assert circuit_open is True


def test_lifecycle_events_update_fan_without_contact_work():
    engine = _engine()
    repository = WebhookEventRepository(engine)

    for event_name, event_id in (
        ("fansly.followers.new", "follow-new"),
        ("fansly.subscriptions.new", "subscription-new"),
        ("fansly.followers.removed", "follow-removed"),
        ("fansly.subscriptions.expired", "subscription-expired"),
    ):
        result = repository.ingest_domain(
            creator_id="creator-a",
            event=_domain_event(event_name, event_id),
        )
        assert result.created is True

    with engine.connect() as connection:
        fan = connection.execute(select(FANS)).mappings().one()
        inbound_count = connection.execute(
            select(func.count(INBOUND_MESSAGES.c.id))
        ).scalar_one()
        outbox_count = connection.execute(
            select(func.count(OUTBOX_MESSAGES.c.id))
        ).scalar_one()
    assert fan["is_follower"] is False
    assert fan["is_subscriber"] is False
    assert inbound_count == 0
    assert outbox_count == 0


@pytest.mark.parametrize(
    "purchase_event_name",
    (
        "fansly.media.purchased",
        "fansly.stories.purchased",
    ),
)
def test_transaction_and_purchase_share_revenue_without_double_counting(
    purchase_event_name,
):
    engine = _engine()
    repository = WebhookEventRepository(engine)

    repository.ingest_domain(
        creator_id="creator-a",
        event=_domain_event(
            "fansly.transactions.new",
            "transaction-event",
            transaction_id="transaction-a",
            reference_id="transaction-a",
        ),
    )
    repository.ingest_domain(
        creator_id="creator-a",
        event=_domain_event(
            purchase_event_name,
            "purchase-event",
            transaction_id="transaction-a",
            reference_id="purchased-content-a",
        ),
    )

    with engine.connect() as connection:
        fan = connection.execute(select(FANS)).mappings().one()
        revenue_rows = connection.execute(
            select(FAN_REVENUE_EVENTS)
        ).mappings().all()
        inbound_count = connection.execute(
            select(func.count(INBOUND_MESSAGES.c.id))
        ).scalar_one()
        outbox_count = connection.execute(
            select(func.count(OUTBOX_MESSAGES.c.id))
        ).scalar_one()
    assert fan["lifetime_value_minor"] == 1234
    assert fan["purchase_count"] == 1
    assert len(revenue_rows) == 1
    assert revenue_rows[0]["ltv_applied"] is True
    assert revenue_rows[0]["purchase_applied"] is True
    assert inbound_count == 0
    assert outbox_count == 0


def test_unattributed_transaction_is_attributed_once_by_purchase():
    engine = _engine()
    repository = WebhookEventRepository(engine)

    repository.ingest_domain(
        creator_id="creator-a",
        event=_domain_event(
            "fansly.transactions.new",
            "transaction-event",
            fan_id=None,
            transaction_id="transaction-a",
            reference_id="transaction-a",
        ),
    )
    purchase = _domain_event(
        "fansly.media.purchased",
        "purchase-event",
        transaction_id="transaction-a",
        reference_id="media-a",
    )
    for _ in range(10):
        repository.ingest_domain(
            creator_id="creator-a",
            event=purchase,
        )

    with engine.connect() as connection:
        fan = connection.execute(select(FANS)).mappings().one()
        revenue = connection.execute(
            select(FAN_REVENUE_EVENTS)
        ).mappings().one()
    assert fan["lifetime_value_minor"] == 1234
    assert fan["purchase_count"] == 1
    assert revenue["fan_id"] == "fan-a"


def test_tip_replay_ten_times_applies_one_financial_effect():
    engine = _engine()
    repository = WebhookEventRepository(engine)
    tip = _domain_event(
        "fansly.tips.received",
        "tip-event",
        transaction_id="tip-transaction-a",
    )

    for _ in range(10):
        result = repository.ingest_domain(
            creator_id="creator-a",
            event=tip,
        )

    assert result.created is False
    with engine.connect() as connection:
        fan = connection.execute(select(FANS)).mappings().one()
        event_count = connection.execute(
            select(func.count(PROVIDER_WEBHOOK_EVENTS.c.id))
        ).scalar_one()
    assert fan["lifetime_value_minor"] == 1234
    assert fan["tip_total_minor"] == 1234
    assert event_count == 1
