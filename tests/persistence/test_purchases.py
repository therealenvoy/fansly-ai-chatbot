from datetime import datetime, timezone

import pytest

from src.fansly_client import WalletTransaction
from src.messaging.models import OutboundMessage
from src.notes.models import FanNote
from src.notes.repository import FanNoteRepository
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.purchases import PurchaseRepository
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository
from src.sequences.models import (
    Sequence,
    SequenceStep,
    SequenceTrigger,
    StepStatus,
)
from src.sequences.repository import SequenceRepository


def _fixture(*, two_steps: bool = False):
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    notes = FanNoteRepository(engine=engine)
    notes.create_table()
    notes.save(FanNote(fan_id="fan-a", creator_id="creator-a"))
    state = ConversationStateRepository(engine)
    state.ensure_conversation("creator-a", "fan-a", "chat-a")
    session, durable = state.load_session("creator-a", "fan-a")
    state.save_state(state.capture_session(session, version=durable.version))
    sequences = SequenceRepository(engine=engine)
    sequences.create_tables()
    sequence = sequences.save_sequence(
        Sequence(
            name="offer",
            trigger=SequenceTrigger.RAPPORT,
            funnel_stage="offer",
        )
    )
    step = sequences.save_step(
        SequenceStep(
            sequence_id=sequence.id,
            position=1,
            media_id="fansly_media_1",
            price=10.0,
            offer_script="unlock",
        )
    )
    sequence.steps = [step]
    if two_steps:
        sequence.steps.append(
            sequences.save_step(
                SequenceStep(
                    sequence_id=sequence.id,
                    position=2,
                    media_id="fansly_media_2",
                    price=20.0,
                    offer_script="unlock more",
                )
            )
        )
    inbox = MessageProcessingRepository(engine)
    inbox.insert_inbound(
        creator_id="creator-a",
        platform_message_id="inbound-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="yes",
        provider_created_at=datetime.now(timezone.utc),
    )
    inbound = inbox.claim_next_inbound("creator-a")
    outbox, _ = inbox.enqueue_outbox(
        inbound=inbound,
        message=OutboundMessage.ppv(
            content="unlock",
            media_ids=("fansly_media_1",),
            price_millis=10_000,
            sequence_id=sequence.id,
            sequence_step_id=step.id,
        ),
    )
    sending = inbox.claim_outbox(outbox.id)
    inbox.complete_delivery(sending.id, "provider-message-1")
    return (
        engine,
        notes,
        state,
        sequences,
        PurchaseRepository(engine),
    )


def test_wallet_ledger_is_idempotent_and_never_creates_purchase():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    repository = PurchaseRepository(engine)
    transactions = [
        WalletTransaction(
            transaction_id="wallet-1",
            transaction_type=2116,
            destination="wallet",
            amount_millis=5000,
            destination_tax_millis=1000,
            new_balance_millis=105000,
            created_at=1780444800000,
            status=1,
        )
    ]

    assert repository.ingest_wallet_transactions(
        "creator-a",
        transactions,
    ) == 1
    assert repository.ingest_wallet_transactions(
        "creator-a",
        transactions,
    ) == 0
    assert repository.count_wallet_transactions("creator-a") == 1
    assert repository.count_purchase_events("creator-a") == 0


def test_attributed_purchase_advances_only_matching_ppv_once():
    _, notes, state, sequences, purchases = _fixture()
    purchased_at = datetime.now(timezone.utc)

    event, created = purchases.record_attributed_purchase(
        creator_id="creator-a",
        provider_purchase_id="purchase-1",
        fan_id="fan-a",
        provider_message_id="provider-message-1",
        amount_millis=10_000,
        source="provider_webhook",
        provider_created_at=purchased_at,
    )

    assert created is True
    assert event.amount_millis == 10_000
    note = notes.get("fan-a", "creator-a")
    assert note.total_spent == 10.0
    assert note.purchase_count == 1
    progress = sequences.get_fan_progress("fan-a", "creator-a")[0]
    assert progress.status == StepStatus.BOUGHT
    assert progress.current_step == 0
    durable = state.load_state("creator-a", "fan-a")
    assert durable.escalation_level == 1
    assert durable.ppvs_bought == 1
    assert durable.purchase_count_seen == 1

    duplicate, created = purchases.record_attributed_purchase(
        creator_id="creator-a",
        provider_purchase_id="purchase-1",
        fan_id="fan-a",
        provider_message_id="provider-message-1",
        amount_millis=10_000,
        source="provider_webhook",
        provider_created_at=purchased_at,
    )

    assert created is False
    assert duplicate.id == event.id
    assert notes.get("fan-a", "creator-a").purchase_count == 1
    assert state.load_state("creator-a", "fan-a").ppvs_bought == 1


def test_attributed_purchase_advances_one_step_at_a_time():
    engine, notes, state, sequences, purchases = _fixture(
        two_steps=True
    )
    purchased_at = datetime.now(timezone.utc)
    purchases.record_attributed_purchase(
        creator_id="creator-a",
        provider_purchase_id="purchase-1",
        fan_id="fan-a",
        provider_message_id="provider-message-1",
        amount_millis=10_000,
        source="provider_attributed",
        provider_created_at=purchased_at,
    )

    progress = sequences.get_fan_progress("fan-a", "creator-a")[0]
    assert progress.current_step == 2
    assert progress.status == StepStatus.PENDING

    sequence = sequences.list_sequences(active_only=True)[0]
    step = sequence.get_step(2)
    inbox = MessageProcessingRepository(engine)
    inbox.insert_inbound(
        creator_id="creator-a",
        platform_message_id="inbound-2",
        fan_id="fan-a",
        chat_id="chat-a",
        content="again",
        provider_created_at=purchased_at,
    )
    inbound = inbox.claim_next_inbound("creator-a")
    outbox, _ = inbox.enqueue_outbox(
        inbound=inbound,
        message=OutboundMessage.ppv(
            content="unlock more",
            media_ids=("fansly_media_2",),
            price_millis=20_000,
            sequence_id=sequence.id,
            sequence_step_id=step.id,
        ),
    )
    inbox.claim_outbox(outbox.id)
    inbox.complete_delivery(outbox.id, "provider-message-2")

    purchases.record_attributed_purchase(
        creator_id="creator-a",
        provider_purchase_id="purchase-2",
        fan_id="fan-a",
        provider_message_id="provider-message-2",
        amount_millis=20_000,
        source="provider_attributed",
        provider_created_at=purchased_at,
    )

    progress = sequences.get_fan_progress("fan-a", "creator-a")[0]
    assert progress.current_step == 0
    assert progress.status == StepStatus.BOUGHT
    assert notes.get("fan-a", "creator-a").total_spent == 30.0
    assert notes.get("fan-a", "creator-a").purchase_count == 2
    durable = state.load_state("creator-a", "fan-a")
    assert durable.escalation_level == 2
    assert durable.ppvs_bought == 2
    assert durable.purchase_count_seen == 2


@pytest.mark.parametrize(
    ("provider_message_id", "amount_millis", "source", "match"),
    [
        ("unknown", 10_000, "provider_webhook", "does not match"),
        (
            "provider-message-1",
            5_000,
            "provider_webhook",
            "amount does not match",
        ),
        (
            "provider-message-1",
            10_000,
            "wallet_ledger",
            "not attributable",
        ),
        (
            "provider-message-1",
            10_000,
            "manual_verified",
            "not attributable",
        ),
    ],
)
def test_purchase_rejects_unattributed_or_mismatched_events(
    provider_message_id,
    amount_millis,
    source,
    match,
):
    _, notes, state, _, purchases = _fixture()

    with pytest.raises(ValueError, match=match):
        purchases.record_attributed_purchase(
            creator_id="creator-a",
            provider_purchase_id="purchase-bad",
            fan_id="fan-a",
            provider_message_id=provider_message_id,
            amount_millis=amount_millis,
            source=source,
            provider_created_at=datetime.now(timezone.utc),
        )

    assert purchases.count_purchase_events("creator-a") == 0
    assert notes.get("fan-a", "creator-a").purchase_count == 0
    assert state.load_state("creator-a", "fan-a").ppvs_bought == 0
