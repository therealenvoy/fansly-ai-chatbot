from types import SimpleNamespace
from unittest.mock import MagicMock, call

from sqlalchemy import select

from src.bot import FanslyBot
from src.fansly_client import ChatInfo, FanslyApiClient, MessageInfo
from src.fansly_client import ProviderCapabilities, WalletTransaction
from src.messaging.models import OutboundMessage
from src.notes.repository import FanNoteRepository
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import (
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    metadata,
)
from src.persistence.state import ConversationStateRepository
from src.sequences.models import (
    Sequence,
    SequenceStep,
    SequenceTrigger,
)


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


def test_controlled_launch_ingests_only_allowlisted_fans():
    engine, bot = _bot()
    bot.require_fan_allowlist = True
    bot.allowed_fan_ids = frozenset({"pilot"})
    allowed = _chat(
        unread_count=1,
        last_message_id="message-1",
        chat_id="allowed-chat",
        fan_id="pilot",
    )
    blocked = _chat(
        unread_count=1,
        last_message_id="message-2",
        chat_id="blocked-chat",
        fan_id="not-pilot",
    )
    bot.client.list_chats_page.return_value = ([blocked, allowed], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot._prepare_message = MagicMock(return_value=None)

    assert bot.poll_and_process() is True

    bot.client.list_messages.assert_called_once_with(
        "allowed-chat",
        limit=100,
        cursor=None,
    )
    rows = _rows(engine, INBOUND_MESSAGES)
    assert [row["fan_id"] for row in rows] == ["pilot"]
    assert bot._chat_cursor_scope().startswith("changed-chats:pilot:")
    assert bot.state_repo.get_poll_cursor(
        "creator-a",
        bot._chat_cursor_scope(),
    ) == bot._chat_checkpoint(allowed)


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


def test_unsupported_ppv_intent_is_preserved_but_never_sent():
    engine, bot = _bot()
    bot.client.capabilities = ProviderCapabilities(
        supports_free_media_messages=True,
        supports_paid_messages=False,
        supports_wallet_transactions=False,
    )
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot._prepare_message = MagicMock(
        return_value=OutboundMessage.ppv(
            content="unlock",
            media_ids=("fansly_media_1",),
            price_millis=10_000,
            sequence_id=1,
            sequence_step_id=1,
        )
    )

    assert bot.poll_and_process() is True

    bot.client.send_message.assert_not_called()
    bot.client.send_ppv.assert_not_called()
    inbound = _rows(engine, INBOUND_MESSAGES)[0]
    outbox = _rows(engine, OUTBOX_MESSAGES)[0]
    assert inbound["status"] == "completed"
    assert outbox["status"] == "blocked_unsupported"
    assert outbox["message_kind"] == "ppv"
    assert outbox["media_ids"] == ["fansly_media_1"]
    assert outbox["price_millis"] == 10_000


def test_documented_free_media_delivery_uses_the_same_outbox():
    engine, bot = _bot()
    bot.client.capabilities = ProviderCapabilities(
        supports_free_media_messages=True,
    )
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot._prepare_message = MagicMock(
        return_value=OutboundMessage.media(
            "look",
            ("fansly_media_1",),
        )
    )
    bot.client.send_message.return_value = SimpleNamespace(
        success=True,
        message_id="provider-media-1",
    )

    assert bot.poll_and_process() is True

    bot.client.send_message.assert_called_once_with(
        "chat-a",
        "look",
        media_ids=[{"mediaId": "fansly_media_1"}],
    )
    outbox = _rows(engine, OUTBOX_MESSAGES)[0]
    assert outbox["status"] == "sent"
    assert outbox["message_kind"] == "media"
    assert outbox["provider_message_id"] == "provider-media-1"


def test_ppv_delivery_forwards_the_sequence_preview_id():
    _, bot = _bot()
    sequence = Sequence(
        name="Preview sequence",
        trigger=SequenceTrigger.WELCOME,
        funnel_stage="offer",
        steps=[
            SequenceStep(
                sequence_id=0,
                position=1,
                media_id="media-1",
                preview_id="preview-1",
                price=25,
            )
        ],
    )
    bot.sequence_repo.save_sequence_with_steps(sequence)
    step = sequence.steps[0]
    outbox = SimpleNamespace(
        chat_id="chat-a",
        message_kind="ppv",
        content="unlock",
        media_ids=["media-1"],
        price_millis=25_000,
        sequence_id=sequence.id,
        sequence_step_id=step.id,
    )
    bot.client.send_ppv.return_value = SimpleNamespace(
        success=True,
        message_id="provider-ppv-1",
    )

    bot._deliver_outbox(outbox)

    bot.client.send_ppv.assert_called_once_with(
        chat_id="chat-a",
        content="unlock",
        media_id="media-1",
        price=25.0,
        preview_id="preview-1",
    )


def test_wallet_sync_is_idempotent_and_does_not_invent_a_buyer():
    engine, bot = _bot()
    bot.client.capabilities = ProviderCapabilities(
        supports_wallet_transactions=True,
    )
    transaction = WalletTransaction(
        transaction_id="wallet-1",
        transaction_type=2116,
        destination="wallet",
        amount_millis=5000,
        destination_tax_millis=1000,
        new_balance_millis=105000,
        created_at=1780444800000,
        status=1,
    )
    bot.client.list_wallet_transactions_page.return_value = (
        [transaction],
        None,
    )
    bot.client.list_chats_page.return_value = ([], None)

    assert bot.poll_and_process() is True
    assert bot.purchase_repo.count_wallet_transactions("creator-a") == 1
    assert bot.purchase_repo.count_purchase_events("creator-a") == 0
    assert bot.poll_and_process() is False
    assert bot.purchase_repo.count_wallet_transactions("creator-a") == 1
