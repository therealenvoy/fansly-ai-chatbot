from datetime import datetime, timezone
import threading

from src.conversation.brain2_memory import LegacyMemoryBackfill
from src.conversation.brain2_memory_async import MemoryExtractionService
from src.conversation.brain2_repository import (
    ConversationEpisodeRepository,
    FanMemoryV2Repository,
)
from src.notes.models import FanNote
from src.persistence.database import create_database_engine
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


def test_legacy_note_backfill_is_idempotent_and_preserves_hard_boundaries():
    engine = _engine()
    repository = FanMemoryV2Repository(engine)
    backfill = LegacyMemoryBackfill(repository)
    note = FanNote(
        fan_id="fan-a",
        creator_id="creator-a",
        preferences=["likes red"],
        hard_limits=["no meetups"],
        facts=["works nights"],
    )

    assert backfill.run(note) == 3
    assert backfill.run(note) == 0

    memories = repository.relevant(
        creator_id="creator-a",
        fan_id="fan-a",
        limit=10,
    )
    assert {item["memory_type"] for item in memories} == {
        "preference",
        "boundary",
        "personal_fact",
    }
    boundary = next(
        item for item in memories if item["memory_type"] == "boundary"
    )
    assert boundary["expires_at"] is None
    assert boundary["source_message_id"].startswith("legacy-note:")


def test_episode_upsert_is_idempotent_and_preserves_source_range():
    engine = _engine()
    repository = ConversationEpisodeRepository(engine)
    now = datetime.now(timezone.utc)
    values = {
        "creator_id": "creator-a",
        "fan_id": "fan-a",
        "episode_key": "m-1:m-10",
        "main_topics": ["work"],
        "emotional_tone": "tired",
        "fan_disclosures": ["night shift"],
        "creator_statements": [],
        "boundaries": [],
        "resolved_threads": [],
        "unresolved_threads": ["how shift ended"],
        "future_callback": "ask about the shift",
        "source_start_message_id": "m-1",
        "source_end_message_id": "m-10",
        "episode_started_at": now,
        "episode_ended_at": now,
    }

    first = repository.save(**values)
    second = repository.save(**values)

    assert first == second
    episode = repository.get(first)
    assert episode["source_start_message_id"] == "m-1"
    assert episode["source_end_message_id"] == "m-10"


def test_memory_extraction_service_is_non_blocking_and_evidence_bound():
    release = threading.Event()
    calls = []

    class Extractor:
        def extract(self, fan_texts):
            release.wait(timeout=2)
            return {"preferences": ["likes horror movies"]}

    class Writer:
        def write(self, **values):
            calls.append(values)

    class Notes:
        def get(self, fan_id, creator_id):
            return None

    service = MemoryExtractionService(
        fact_extractor=Extractor(),
        memory_writer=Writer(),
        note_repository=Notes(),
        note_extractor=object(),
    )

    assert service.submit(
        creator_id="creator-a",
        fan_id="fan-a",
        fan_texts=["I like horror movies"],
        source_message_id="m-9",
        source_timestamp=datetime.now(timezone.utc),
    ) is True
    assert calls == []
    release.set()
    service.wait_for_idle()
    service.shutdown()

    assert calls[0]["source_message_id"] == "m-9"
    assert calls[0]["fan_id"] == "fan-a"
