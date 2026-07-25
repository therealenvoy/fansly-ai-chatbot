from unittest.mock import MagicMock

from src.bot import FanslyBot
from src.fansly_client import ChatInfo, FanslyApiClient, MessageInfo
from src.memory.store import MessageStore
from src.notes.models import FanNote
from src.notes.repository import FanNoteRepository
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository


def _durable_bot(engine):
    client = MagicMock(spec=FanslyApiClient)
    client.account_id = "account-a"

    persona = MagicMock()
    persona.forbidden_phrases = []
    persona.pet_names = ["babe"]
    persona.common_typos = {}
    persona_loader = MagicMock()
    persona_loader.load.return_value = persona

    note_repo = FanNoteRepository(engine=engine)
    note_repo.create_table()
    note_repo.save(
        FanNote(
            fan_id="fan-a",
            creator_id="creator-a",
            relationship_stage="classified_chatty_fan",
        )
    )
    message_store = MessageStore(engine=engine)
    message_store.create_table()
    state_repo = ConversationStateRepository(engine)

    bot = FanslyBot(
        client=client,
        persona_loader=persona_loader,
        note_repo=note_repo,
        creator_id="creator-a",
        message_store=message_store,
        state_repo=state_repo,
    )
    return bot


def test_bot_session_and_dedup_survive_restart():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    chat = ChatInfo(
        chat_id="chat-a",
        partner_account_id="fan-a",
        partner_username="fan",
        partner_display_name="Fan",
        unread_count=1,
    )
    message = MessageInfo(
        message_id="message-a",
        content="hello",
        sender_id="fan-a",
        created_at=1000,
        is_from_fan=True,
    )

    first = _durable_bot(engine)
    first.client.get_all_chats.return_value = [chat]
    first.client.list_messages.return_value = ([message], None)
    first._generate_reply = MagicMock(return_value="hello back")
    first.poll_and_process()

    assert first.state_repo.has_processed("creator-a", "message-a")
    _, stored = first.state_repo.load_session("creator-a", "fan-a")
    assert stored.message_count == 2

    second = _durable_bot(engine)
    second.client.get_all_chats.return_value = [chat]
    second.client.list_messages.return_value = ([message], None)
    second._generate_reply = MagicMock(return_value="duplicate")
    second.poll_and_process()

    second._generate_reply.assert_not_called()
    restored_session = second.sessions["fan-a"]
    assert restored_session.message_count == 2
