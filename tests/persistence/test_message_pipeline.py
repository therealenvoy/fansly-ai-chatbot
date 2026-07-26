from types import SimpleNamespace
from unittest.mock import MagicMock, call

from sqlalchemy import select

from src.bot import FanslyBot
from src.fansly_client import ChatInfo, FanslyApiClient, MessageInfo
from src.notes.repository import FanNoteRepository
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import (
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    metadata,
)
from src.persistence.state import ConversationStateRepository


def _bot():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
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
    state_repo = ConversationStateRepository(engine)
    bot = FanslyBot(
        client=client,
        persona_loader=persona_loader,
        note_repo=note_repo,
        creator_id="creator-a",
        state_repo=state_repo,
    )
    bot._persist_runtime_state = MagicMock()
    return engine, bot


def _chat(
    *,
    unread_count,
    last_message_id,
    chat_id="chat-a",
    fan_id="fan-a",
):
    return ChatInfo(
        chat_id=chat_id,
        partner_account_id=fan_id,
        partner_username="fan",
        partner_display_name="Fan",
        unread_count=unread_count,
        last_message_id=last_message_id,
    )


def _message(number, *, fan=True, content=None):
    return MessageInfo(
        message_id=f"message-{number}",
        content=content if content is not None else f"inbound-{number}",
        sender_id="fan-a" if fan else "account-a",
        created_at=float(number),
        is_from_fan=fan,
    )


def _rows(engine, table):
    with engine.connect() as conn:
        return conn.execute(
            select(table).order_by(table.c.id)
        ).mappings().all()


def test_pipeline_sorts_oldest_first_and_sends_every_message_once():
    engine, bot = _bot()
    chat = _chat(unread_count=3, last_message_id="message-3")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(3), _message(2), _message(1)],
        None,
    )
    bot._prepare_message = MagicMock(
        side_effect=lambda _chat, message, _messages: (
            f"reply-{message.message_id}"
        )
    )
    bot.client.send_message.side_effect = [
        SimpleNamespace(success=True, message_id="provider-reply-1"),
        SimpleNamespace(success=True, message_id="provider-reply-2"),
        SimpleNamespace(success=True, message_id="provider-reply-3"),
    ]

    assert bot.poll_and_process() is True

    assert [
        item.args[1].message_id
        for item in bot._prepare_message.call_args_list
    ] == ["message-1", "message-2", "message-3"]
    assert bot.client.send_message.call_args_list == [
        call("chat-a", "reply-message-1"),
        call("chat-a", "reply-message-2"),
        call("chat-a", "reply-message-3"),
    ]
    inbound = _rows(engine, INBOUND_MESSAGES)
    outbox = _rows(engine, OUTBOX_MESSAGES)
    assert [row["status"] for row in inbound] == [
        "completed",
        "completed",
        "completed",
    ]
    assert [row["provider_message_id"] for row in outbox] == [
        "provider-reply-1",
        "provider-reply-2",
        "provider-reply-3",
    ]

    bot._prepare_message.reset_mock()
    assert bot.poll_and_process() is False
    bot._prepare_message.assert_not_called()
    assert bot.client.send_message.call_count == 3


def test_first_scan_processes_only_the_provider_unread_window():
    engine, bot = _bot()
    chat = _chat(unread_count=2, last_message_id="message-5")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(number) for number in range(5, 0, -1)],
        None,
    )
    bot._prepare_message = MagicMock(
        side_effect=lambda _chat, message, _messages: (
            f"reply-{message.message_id}"
        )
    )
    bot.client.send_message.side_effect = [
        SimpleNamespace(success=True, message_id="provider-reply-4"),
        SimpleNamespace(success=True, message_id="provider-reply-5"),
    ]

    bot.poll_and_process()

    assert [
        item.args[1].message_id
        for item in bot._prepare_message.call_args_list
    ] == ["message-4", "message-5"]
    assert [
        row["platform_message_id"]
        for row in _rows(engine, INBOUND_MESSAGES)
    ] == ["message-4", "message-5"]


def test_changed_read_chat_ingests_messages_after_its_checkpoint():
    engine, bot = _bot()
    chat = _chat(unread_count=0, last_message_id="message-2")
    bot.state_repo.ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    bot.state_repo.update_conversation_checkpoint(
        "creator-a",
        "chat-a",
        last_platform_message_id="message-1",
    )
    bot.state_repo.set_poll_cursor(
        "creator-a",
        "changed-chats",
        bot._chat_checkpoint(
            _chat(unread_count=0, last_message_id="message-1")
        ),
    )
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(2), _message(1)],
        None,
    )
    bot._prepare_message = MagicMock(return_value="reply")
    bot.client.send_message.return_value = SimpleNamespace(
        success=True,
        message_id="provider-reply-2",
    )

    assert bot.poll_and_process() is True

    bot._prepare_message.assert_called_once()
    assert (
        bot._prepare_message.call_args.args[1].message_id
        == "message-2"
    )
    assert [
        row["platform_message_id"]
        for row in _rows(engine, INBOUND_MESSAGES)
    ] == ["message-2"]


def test_invalid_inbound_completes_without_generation_or_outbox():
    engine, bot = _bot()
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(1, content=" \r\n ")],
        None,
    )
    bot._prepare_message = MagicMock(return_value="must not be used")

    bot.poll_and_process()

    bot._prepare_message.assert_not_called()
    bot.client.send_message.assert_not_called()
    assert _rows(engine, INBOUND_MESSAGES)[0]["status"] == "completed"
    assert _rows(engine, OUTBOX_MESSAGES) == []


def test_empty_decision_completes_without_outbox():
    engine, bot = _bot()
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot._prepare_message = MagicMock(return_value=None)

    bot.poll_and_process()

    bot.client.send_message.assert_not_called()
    assert _rows(engine, INBOUND_MESSAGES)[0]["status"] == "completed"
    assert _rows(engine, OUTBOX_MESSAGES) == []


def test_uncertain_provider_failure_is_never_automatically_retried():
    engine, bot = _bot()
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot._prepare_message = MagicMock(return_value="reply")
    bot.client.send_message.side_effect = TimeoutError(
        "provider timed out after request"
    )

    assert bot.poll_and_process() is True
    assert MessageProcessingRepository(engine).counts("creator-a") == {
        "inbound_failed": 1,
        "outbox_delivery_unknown": 1,
    }

    bot._prepare_message.reset_mock()
    assert bot.poll_and_process() is False
    bot._prepare_message.assert_not_called()
    assert bot.client.send_message.call_count == 1
