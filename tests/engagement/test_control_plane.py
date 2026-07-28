from datetime import datetime, timezone
import pytest
from sqlalchemy import func, select

from src.engagement.control_plane import (
    ContactClaimRepository,
    NativePlanRepository,
    OwnershipConflict,
    TriggerOwner,
    TriggerOwnershipRepository,
    TriggerType,
)
from src.persistence.database import create_database_engine
from src.persistence.schema import (
    CONTACT_CLAIMS,
    NATIVE_AUTOMATIONS,
    TRIGGER_OWNERSHIP_EVENTS,
    metadata,
)
from src.persistence.pipeline import MessageProcessingRepository, OUTBOX_BLOCKED_POLICY
from src.persistence.state import ConversationStateRepository


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    return engine


def test_trigger_owner_must_be_disabled_before_reassignment():
    engine = _engine()
    repository = TriggerOwnershipRepository(engine)
    repository.assign(
        "creator-a",
        TriggerType.NEW_FOLLOWER,
        TriggerOwner.FANSLY_NATIVE_AUTOMATION,
        actor="operator",
        reason="native plan",
    )

    with pytest.raises(OwnershipConflict, match="disable"):
        repository.assign(
            "creator-a",
            TriggerType.NEW_FOLLOWER,
            TriggerOwner.BRAIN2,
            actor="operator",
            reason="conflicting plan",
        )

    repository.assign(
        "creator-a",
        TriggerType.NEW_FOLLOWER,
        TriggerOwner.DISABLED,
        actor="operator",
        reason="handover",
    )
    assigned = repository.assign(
        "creator-a",
        TriggerType.NEW_FOLLOWER,
        TriggerOwner.BRAIN2,
        actor="operator",
        reason="handover complete",
    )
    assert assigned.owner == TriggerOwner.BRAIN2
    assert assigned.version == 3
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count(TRIGGER_OWNERSHIP_EVENTS.c.id))
        ).scalar_one() == 3


def test_same_episode_cannot_be_claimed_by_native_and_brain():
    engine = _engine()
    repository = ContactClaimRepository(engine)
    native = repository.claim(
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_type=TriggerType.NEW_FOLLOWER,
        trigger_event_id="follow-event-a",
        source_system=TriggerOwner.FANSLY_NATIVE_AUTOMATION,
    )
    brain = repository.claim(
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_type=TriggerType.NEW_FOLLOWER,
        trigger_event_id="follow-event-a",
        source_system=TriggerOwner.BRAIN2,
    )
    repeat_native = repository.claim(
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_type=TriggerType.NEW_FOLLOWER,
        trigger_event_id="follow-event-a",
        source_system=TriggerOwner.FANSLY_NATIVE_AUTOMATION,
    )

    assert native.granted is True
    assert brain.granted is False
    assert brain.denial_reason == "episode_already_claimed"
    assert repeat_native.granted is True
    assert repeat_native.claim_id == native.claim_id
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count(CONTACT_CLAIMS.c.id))
        ).scalar_one() == 1


def test_native_plan_is_truthful_and_rejects_undocumented_online_trigger():
    engine = _engine()
    repository = NativePlanRepository(engine)

    with pytest.raises(ValueError, match="not a documented"):
        repository.create_automation(
            creator_id="creator-a",
            name="online opener",
            trigger_type=TriggerType.ONLINE,
            message_text="hello",
        )

    plan_id = repository.create_automation(
        creator_id="creator-a",
        name="new follower welcome",
        trigger_type=TriggerType.NEW_FOLLOWER,
        message_text="welcome",
    )
    with engine.connect() as connection:
        row = connection.execute(
            select(NATIVE_AUTOMATIONS).where(
                NATIVE_AUTOMATIONS.c.id == plan_id
            )
        ).mappings().one()
    assert row["configuration_status"] == "draft"
    assert row["intended_enabled"] is False
    assert row["provider_automation_id"] is None
    assert row["message_hash"] == repository.fingerprint("welcome")


def _pending_outbox(engine):
    repository = MessageProcessingRepository(engine)
    inbound, _ = repository.insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-a",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hello",
        provider_created_at=datetime.now(timezone.utc),
    )
    claimed = repository.claim_next_inbound("creator-a")
    outbox, _ = repository.enqueue_outbox(
        inbound=claimed,
        content="reply",
        service_role=TriggerOwner.CURRENT_BRAIN.value,
    )
    return repository, outbox


def test_sender_rechecks_trigger_owner_inside_claim_transaction():
    engine = _engine()
    repository, outbox = _pending_outbox(engine)
    owners = TriggerOwnershipRepository(engine)
    owners.assign(
        "creator-a",
        TriggerType.INBOUND_REPLY,
        TriggerOwner.DISABLED,
        actor="operator",
        reason="kill switch",
    )

    assert repository.claim_outbox(outbox.id) is None
    blocked = repository.get_outbox_for_inbound(outbox.inbound_message_id)
    assert blocked.status == OUTBOX_BLOCKED_POLICY
    assert blocked.permit_status == "revoked"


def test_sender_rejects_episode_claimed_by_another_system():
    engine = _engine()
    repository, outbox = _pending_outbox(engine)
    ContactClaimRepository(engine).claim(
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_type=TriggerType.INBOUND_REPLY,
        trigger_event_id="message-a",
        source_system=TriggerOwner.FANSLY_NATIVE_AUTOMATION,
    )

    assert repository.claim_outbox(outbox.id) is None
    blocked = repository.get_outbox_for_inbound(outbox.inbound_message_id)
    assert blocked.status == OUTBOX_BLOCKED_POLICY
