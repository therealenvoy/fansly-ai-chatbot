from datetime import datetime, timedelta, timezone

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


def _sent_turn(engine):
    now = datetime.now(timezone.utc)
    pipeline = MessageProcessingRepository(engine)
    inbound, _ = pipeline.insert_inbound(
        creator_id="creator-a",
        platform_message_id="inbound-1",
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
        provider_message_id="outbound-1",
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
