from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from src.conversation.brain2_schema import CONVERSATION_OUTCOMES
from src.conversation.brain2_repository import (
    ConversationOutcomeRepository,
    FanConversationStateRepository,
    FanMemoryV2Repository,
    PersistentExperimentRepository,
)
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    return engine


def _sent_turn(engine, suffix="1"):
    now = datetime.now(timezone.utc)
    pipeline = MessageProcessingRepository(engine)
    inbound, _ = pipeline.insert_inbound(
        creator_id="creator-a",
        platform_message_id=f"inbound-{suffix}",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hello",
        provider_created_at=now,
    )
    outbox, _ = pipeline.enqueue_outbox(
        inbound=inbound,
        message=__import__(
            "src.messaging.models",
            fromlist=["OutboundMessage"],
        ).OutboundMessage.text("hey"),
    )
    pipeline.claim_outbox(outbox.id)
    pipeline.complete_delivery(
        outbox.id,
        provider_message_id=f"outbound-{suffix}",
    )
    return inbound.id, outbox.id, now


def test_outcome_attributes_reply_to_newest_eligible_sent_turn_once():
    engine = _engine()
    inbound_id, outbox_id, sent_at = _sent_turn(engine)
    repository = ConversationOutcomeRepository(engine)
    first = repository.create_for_delivery(
        decision_id=None,
        inbound_message_id=inbound_id,
        outbox_message_id=outbox_id,
        creator_id="creator-a",
        fan_id="fan-a",
        brain_version="current",
        model="deepseek-v4-flash",
        trigger_kind="unread",
        sent_at=sent_at,
    )

    attributed = repository.attribute_inbound_reply(
        creator_id="creator-a",
        fan_id="fan-a",
        inbound_message_id=999,
        received_at=sent_at + timedelta(seconds=45),
        meaningful=True,
    )
    duplicate = repository.attribute_inbound_reply(
        creator_id="creator-a",
        fan_id="fan-a",
        inbound_message_id=999,
        received_at=sent_at + timedelta(seconds=45),
        meaningful=True,
    )

    assert attributed == first
    assert duplicate == first
    stored = repository.get(first)
    assert stored["fan_replied"] is True
    assert stored["reply_latency_seconds"] == 45
    assert stored["reply_inbound_message_id"] == 999
    assert stored["returned_within_24h"] is True


def test_outcome_progress_is_recomputed_from_durable_inbound_rows():
    engine = _engine()
    inbound_id, outbox_id, sent_at = _sent_turn(engine)
    repository = ConversationOutcomeRepository(engine)
    outcome_id = repository.create_for_delivery(
        decision_id=None,
        inbound_message_id=inbound_id,
        outbox_message_id=outbox_id,
        creator_id="creator-a",
        fan_id="fan-a",
        brain_version="current",
        model="deepseek-v4-flash",
        trigger_kind="stalled",
        sent_at=sent_at,
    )
    pipeline = MessageProcessingRepository(engine)
    for index in range(3):
        inbound, created = pipeline.insert_inbound(
            creator_id="creator-a",
            platform_message_id=f"reply-{index}",
            fan_id="fan-a",
            chat_id="chat-a",
            content="stop" if index == 2 else "yes",
            provider_created_at=sent_at + timedelta(minutes=index + 1),
        )
        assert created is True
        repository.attribute_inbound_reply(
            creator_id="creator-a",
            fan_id="fan-a",
            inbound_message_id=inbound.id,
            received_at=sent_at + timedelta(minutes=index + 1),
            meaningful=True,
            negative_signal=index == 2,
        )

    stored = repository.get(outcome_id)
    assert stored["additional_turns"] == 3
    assert stored["continued_three_turns"] is True
    assert stored["stalled_recovered"] is True
    assert stored["negative_signal"] is True


def test_outcome_window_closes_expired_rows():
    engine = _engine()
    inbound_id, outbox_id, sent_at = _sent_turn(engine)
    repository = ConversationOutcomeRepository(engine)
    outcome_id = repository.create_for_delivery(
        decision_id=None,
        inbound_message_id=inbound_id,
        outbox_message_id=outbox_id,
        creator_id="creator-a",
        fan_id="fan-a",
        brain_version="current",
        model="deepseek-v4-flash",
        trigger_kind="unread",
        sent_at=sent_at - timedelta(hours=25),
    )

    assert repository.close_expired(
        creator_id="creator-a",
        now=sent_at,
        window_hours=24,
    ) == 1
    closed_at = repository.get(outcome_id)["attribution_closed_at"]
    if closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=timezone.utc)
    assert closed_at == sent_at


def test_rollback_summary_is_variant_scoped_and_uses_closed_outcomes():
    engine = _engine()
    repository = ConversationOutcomeRepository(engine)
    outcome_ids = []
    for suffix, variant in (("control", "control"), ("advanced", "advanced")):
        inbound_id, outbox_id, sent_at = _sent_turn(engine, suffix)
        outcome_ids.append(
            repository.create_for_delivery(
                decision_id=None,
                inbound_message_id=inbound_id,
                outbox_message_id=outbox_id,
                creator_id="creator-a",
                fan_id="fan-a",
                brain_version="brain2-v2",
                model="deepseek-v4-flash",
                variant=variant,
                trigger_kind="unread",
                sent_at=sent_at,
            )
        )
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            update(CONVERSATION_OUTCOMES)
            .where(CONVERSATION_OUTCOMES.c.id.in_(outcome_ids))
            .values(
                meaningful_reply=True,
                continued_three_turns=True,
                attribution_closed_at=now,
            )
        )

    summary = repository.rollback_summary(creator_id="creator-a")

    assert summary["control"]["attempts"] == 1
    assert summary["advanced"]["attempts"] == 1
    assert summary["control"]["meaningful_replies"] == 1
    assert summary["advanced"]["continuations"] == 1


def test_memory_supersedes_conflict_and_keeps_source_provenance():
    engine = _engine()
    repository = FanMemoryV2Repository(engine)
    first = repository.remember(
        creator_id="creator-a",
        fan_id="fan-a",
        memory_type="preference",
        normalized_value="favorite_color=blue",
        display_value="Favorite color is blue",
        confidence=0.9,
        importance=0.7,
        source_message_id="m-1",
        source_timestamp=datetime.now(timezone.utc),
    )
    second = repository.remember(
        creator_id="creator-a",
        fan_id="fan-a",
        memory_type="preference",
        normalized_value="favorite_color=red",
        display_value="Favorite color is red",
        confidence=1.0,
        importance=0.8,
        source_message_id="m-2",
        source_timestamp=datetime.now(timezone.utc),
        contradiction_key="favorite_color",
    )

    assert second != first
    active = repository.relevant(
        creator_id="creator-a",
        fan_id="fan-a",
        limit=10,
    )
    assert [item["display_value"] for item in active] == [
        "Favorite color is red"
    ]
    old = repository.get(first)
    assert old["status"] == "superseded"
    assert old["superseded_by_id"] == second
    corrected = repository.correct(
        second,
        creator_id="creator-a",
        display_value="Favorite color is burgundy",
        confidence=0.95,
        contradiction_status="operator_confirmed",
    )
    assert corrected["display_value"] == "Favorite color is burgundy"
    assert corrected["source_message_id"] == "m-2"
    assert corrected["source_event_id"].startswith("crm-correction:")
    assert repository.deactivate(
        second,
        creator_id="creator-a",
    ) is True
    assert repository.relevant(
        creator_id="creator-a",
        fan_id="fan-a",
        limit=10,
    ) == []


def test_state_update_uses_optimistic_versioning():
    engine = _engine()
    repository = FanConversationStateRepository(engine)
    initial = repository.get_or_create("creator-a", "fan-a")

    updated = repository.update(
        creator_id="creator-a",
        fan_id="fan-a",
        expected_version=initial["state_version"],
        changes={"current_objective": "deepen", "question_streak": 1},
    )

    assert updated["state_version"] == initial["state_version"] + 1
    assert repository.update(
        creator_id="creator-a",
        fan_id="fan-a",
        expected_version=initial["state_version"],
        changes={"current_objective": "repair"},
    ) is None


def test_experiment_assignment_is_sticky_and_pause_safe():
    engine = _engine()
    repository = PersistentExperimentRepository(engine)
    experiment_id = repository.create(
        creator_id="creator-a",
        name="brain-version",
        variants={"control": 50, "brain2": 50},
        minimum_sample_size=100,
    )

    first = repository.assign(
        experiment_id=experiment_id,
        creator_id="creator-a",
        fan_id="fan-a",
    )
    second = repository.assign(
        experiment_id=experiment_id,
        creator_id="creator-a",
        fan_id="fan-a",
    )
    repository.pause(experiment_id, creator_id="creator-a")

    assert first == second
    assert repository.assign(
        experiment_id=experiment_id,
        creator_id="creator-a",
        fan_id="fan-b",
    ) is None
    events = repository.events(
        experiment_id=experiment_id,
        creator_id="creator-a",
    )
    assert [event["event_type"] for event in events] == ["created", "paused"]
