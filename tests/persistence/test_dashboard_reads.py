from datetime import datetime, timedelta, timezone

from src.notes.models import FanNote
from src.notes.repository import FanNoteRepository
from src.persistence.dashboard import DashboardReadRepository
from src.persistence.database import create_database_engine
from src.persistence.schema import (
    CONVERSATIONS,
    CREATORS,
    FANS,
    FAN_MESSAGES,
    FAN_RUNTIME_STATES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROVIDER_WALLET_TRANSACTIONS,
    PURCHASE_EVENTS,
    metadata,
)


def _repository():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    notes = FanNoteRepository(engine=engine)
    notes.create_table()
    notes.save(
        FanNote(
            fan_id="fan-a",
            creator_id="creator-a",
            total_spent=999.0,
            purchase_count=99,
        )
    )
    started = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            CREATORS.insert().values(
                id="creator-a",
                created_at=started,
                updated_at=started,
            )
        )
        conn.execute(
            FANS.insert().values(
                creator_id="creator-a",
                fan_id="fan-a",
                created_at=started,
                updated_at=started,
            )
        )
        conn.execute(
            CONVERSATIONS.insert().values(
                creator_id="creator-a",
                chat_id="chat-a",
                fan_id="fan-a",
                last_activity_at=started,
                created_at=started,
                updated_at=started,
            )
        )
        conn.execute(
            FAN_RUNTIME_STATES.insert().values(
                creator_id="creator-a",
                fan_id="fan-a",
                phase="offer",
                phase_history=["rapport", "offer"],
                messages_in_phase=2,
                escalation_level=3,
                ppvs_bought=1,
                cooldown=False,
                consecutive_rejections=0,
                warmup=False,
                last_activity_at=started,
                message_count=8,
                extract_counter=2,
                purchase_count_seen=1,
                rhythm_phase_history=["pull"],
                rhythm_push_count=1,
                rhythm_pull_count=1,
                version=2,
                created_at=started,
                updated_at=started,
            )
        )
        for index in range(8):
            conn.execute(
                FAN_MESSAGES.insert().values(
                    fan_id="fan-a",
                    creator_id="creator-a",
                    chat_id="chat-a",
                    sender="fan" if index % 2 == 0 else "creator",
                    content=f"stored-{index}",
                    message_id=f"stored-{index}",
                    attachments=[],
                    created_at=started + timedelta(seconds=index),
                )
            )
        inbound_ids = []
        for index in range(3):
            result = conn.execute(
                INBOUND_MESSAGES.insert().values(
                    creator_id="creator-a",
                    platform_message_id=f"inbound-{index}",
                    fan_id="fan-a",
                    chat_id="chat-a",
                    content="hello",
                    provider_created_at=started,
                    observed_at=started,
                    status="completed",
                    attempt_count=1,
                    completed_at=started
                    + timedelta(seconds=10 + index),
                )
            )
            inbound_ids.append(result.inserted_primary_key[0])
        text_result = conn.execute(
            OUTBOX_MESSAGES.insert().values(
                inbound_message_id=inbound_ids[0],
                creator_id="creator-a",
                fan_id="fan-a",
                chat_id="chat-a",
                content="hi",
                message_kind="text",
                media_ids=[],
                status="sent",
                provider_message_id="sent-text",
                attempt_count=1,
                created_at=started,
                sent_at=started + timedelta(seconds=10),
            )
        )
        assert text_result.inserted_primary_key[0]
        ppv_result = conn.execute(
            OUTBOX_MESSAGES.insert().values(
                inbound_message_id=inbound_ids[1],
                creator_id="creator-a",
                fan_id="fan-a",
                chat_id="chat-a",
                content="unlock",
                message_kind="ppv",
                media_ids=["fansly_media_1"],
                price_millis=10_000,
                sequence_id=1,
                sequence_step_id=1,
                status="sent",
                provider_message_id="sent-ppv",
                attempt_count=1,
                created_at=started,
                sent_at=started + timedelta(seconds=20),
            )
        )
        ppv_outbox_id = ppv_result.inserted_primary_key[0]
        conn.execute(
            OUTBOX_MESSAGES.insert().values(
                inbound_message_id=inbound_ids[2],
                creator_id="creator-a",
                fan_id="fan-a",
                chat_id="chat-a",
                content="blocked",
                message_kind="ppv",
                media_ids=["fansly_media_2"],
                price_millis=20_000,
                sequence_id=1,
                sequence_step_id=2,
                status="blocked_unsupported",
                attempt_count=0,
                created_at=started,
            )
        )
        conn.execute(
            PURCHASE_EVENTS.insert().values(
                creator_id="creator-a",
                provider_purchase_id="purchase-1",
                fan_id="fan-a",
                outbox_message_id=ppv_outbox_id,
                provider_message_id="sent-ppv",
                amount_millis=10_000,
                source="provider_attributed",
                provider_created_at=started
                + timedelta(seconds=30),
                applied_at=started + timedelta(seconds=31),
            )
        )
        conn.execute(
            PROVIDER_WALLET_TRANSACTIONS.insert().values(
                creator_id="creator-a",
                provider_transaction_id="wallet-1",
                transaction_type=2116,
                destination="wallet",
                amount_millis=10_000,
                destination_tax_millis=2_000,
                new_balance_millis=100_000,
                provider_created_at=started,
                provider_status=1,
                observed_at=started,
            )
        )
    return DashboardReadRepository(engine)


def test_fan_totals_ignore_unattributed_legacy_note_values():
    totals = _repository().fan_purchase_totals("creator-a")

    assert totals["fan-a"].purchase_count == 1
    assert totals["fan-a"].total_spent_millis == 10_000


def test_metrics_are_derived_from_durable_events_without_invented_values():
    metrics = _repository().metrics("creator-a")

    assert metrics.known_fans == 1
    assert metrics.completed_inbounds == 3
    assert metrics.sent_outbounds == 2
    assert metrics.text_sends == 1
    assert metrics.media_sends == 0
    assert metrics.ppv_sends == 1
    assert metrics.blocked_ppv_intents == 1
    assert metrics.attributed_purchases == 1
    assert metrics.attributed_revenue_millis == 10_000
    assert metrics.average_order_value_millis == 10_000
    assert metrics.ppv_unlock_rate == 100.0
    assert metrics.average_response_seconds == 15.0
    assert metrics.wallet_transactions == 1
    assert metrics.wallet_latest_balance_millis == 100_000


def test_conversation_summaries_come_from_durable_state():
    conversations = _repository().conversations("creator-a")

    assert len(conversations) == 1
    assert conversations[0].fan_id == "fan-a"
    assert conversations[0].phase == "offer"
    assert conversations[0].escalation_level == 3
    assert conversations[0].message_count == 8


def test_conversation_page_is_tenant_scoped_searchable_and_paginated():
    repository = _repository()
    now = datetime.now(timezone.utc)
    with repository.engine.begin() as connection:
        for index, username in enumerate(("amber", "bella", "cassie")):
            fan_id = f"fan-{index}"
            connection.execute(
                FANS.insert().values(
                    creator_id="creator-a",
                    fan_id=fan_id,
                    display_name=username.title(),
                    username=username,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                CONVERSATIONS.insert().values(
                    creator_id="creator-a",
                    chat_id=f"chat-{index}",
                    fan_id=fan_id,
                    last_activity_at=now + timedelta(minutes=index),
                    created_at=now,
                    updated_at=now,
                )
            )
        connection.execute(
            CREATORS.insert().values(
                id="creator-b",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            FANS.insert().values(
                creator_id="creator-b",
                fan_id="foreign-fan",
                username="foreign",
                created_at=now,
                updated_at=now,
            )
        )

    first = repository.conversation_page(
        "creator-a",
        limit=2,
        offset=0,
    )
    second = repository.conversation_page(
        "creator-a",
        limit=2,
        offset=2,
    )
    searched = repository.conversation_page(
        "creator-a",
        limit=10,
        search="BEL",
    )

    assert first.total == 4
    assert first.has_more is True
    assert [row.username for row in first.conversations] == [
        "cassie",
        "bella",
    ]
    assert second.has_more is False
    assert {row.fan_id for row in second.conversations} == {
        "fan-0",
        "fan-a",
    }
    assert [row.username for row in searched.conversations] == ["bella"]
