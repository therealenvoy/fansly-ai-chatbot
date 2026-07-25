import pytest

from src.funnel.spiral import SpiralPhase
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import (
    ConcurrentStateUpdate,
    ConversationStateRepository,
)
from src.rhythm.engine import RhythmPhase


def _repo():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    return ConversationStateRepository(engine)


def test_session_state_survives_repository_reconstruction():
    repo = _repo()
    session, state = repo.load_session("creator-a", "fan-a")
    session.add_message("subscriber", "hello")
    session.funnel.transition(SpiralPhase.TEASE)
    session.funnel.level.number = 3
    session.funnel.level.ppvs_bought = 2
    session.funnel.enter_cooldown()
    state = repo.capture_session(
        session,
        extract_counter=2,
        purchase_count_seen=4,
        version=state.version,
    )
    repo.save_state(state)

    reconstructed = ConversationStateRepository(repo.engine)
    loaded_session, loaded_state = reconstructed.load_session(
        "creator-a",
        "fan-a",
    )

    assert loaded_session.funnel.current_stage == SpiralPhase.TEASE
    assert loaded_session.funnel.level.number == 3
    assert loaded_session.funnel.level.ppvs_bought == 2
    assert loaded_session.funnel.cooldown is True
    assert loaded_session.message_count == 1
    assert loaded_state.extract_counter == 2
    assert loaded_state.purchase_count_seen == 4


def test_rhythm_state_survives_restart():
    repo = _repo()
    session, state = repo.load_session("creator-a", "fan-a")
    rhythm = repo.restore_rhythm(state)
    rhythm.next()
    saved = repo.capture_session(session, rhythm=rhythm, version=state.version)
    repo.save_state(saved)

    _, loaded = repo.load_session("creator-a", "fan-a")
    restored = repo.restore_rhythm(loaded)

    assert restored.current_phase == RhythmPhase.PUSH
    assert restored.push_count == 1


def test_processed_platform_message_is_durable_and_unique():
    repo = _repo()

    assert repo.mark_processed("creator-a", "message-1", "fan-a", "chat-a")
    assert not repo.mark_processed(
        "creator-a",
        "message-1",
        "fan-a",
        "chat-a",
    )
    assert repo.has_processed("creator-a", "message-1")

    reconstructed = ConversationStateRepository(repo.engine)
    assert reconstructed.has_processed("creator-a", "message-1")


def test_conversation_identity_is_upserted():
    repo = _repo()

    repo.ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
        display_name="Fan A",
    )
    repo.ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
        display_name="Updated",
    )


def test_stale_runtime_state_write_is_rejected():
    repo = _repo()
    session, initial = repo.load_session("creator-a", "fan-a")
    repo.save_state(repo.capture_session(session, version=initial.version))

    _, first_copy = repo.load_session("creator-a", "fan-a")
    _, stale_copy = repo.load_session("creator-a", "fan-a")
    first_copy.extract_counter = 1
    repo.save_state(first_copy)

    stale_copy.extract_counter = 2
    with pytest.raises(ConcurrentStateUpdate):
        repo.save_state(stale_copy)


def test_poll_cursor_is_creator_scoped_and_survives_restart():
    repo = _repo()
    repo.set_poll_cursor("creator-a", "changed-chats", "cursor-a")
    repo.set_poll_cursor("creator-b", "changed-chats", "cursor-b")

    reconstructed = ConversationStateRepository(repo.engine)
    assert (
        reconstructed.get_poll_cursor("creator-a", "changed-chats")
        == "cursor-a"
    )
    assert (
        reconstructed.get_poll_cursor("creator-b", "changed-chats")
        == "cursor-b"
    )
