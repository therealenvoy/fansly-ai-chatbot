from types import SimpleNamespace
from unittest.mock import MagicMock, call
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.bot import FanslyBot
from src.conversation.mode import BotMode
from src.conversation.brain import ConversationDecision
from src.conversation.brain2_schema import CONVERSATION_OUTCOMES
from src.engagement.control_plane import (
    TriggerOwner,
    TriggerOwnershipRepository,
    TriggerType,
)
from src.fansly_client import (
    ChatInfo,
    FanslyApiClient,
    MessageInfo,
    UserPresence,
)
from src.fansly_client import ProviderCapabilities, WalletTransaction
from src.messaging.models import OutboundMessage
from src.memory.store import MessageStore
from src.notes.repository import FanNoteRepository
from src.persistence.crm import CrmSyncRepository
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
from src.webhooks.onlyfansapi import OnlyFansApiFanslyMessage


def _bot(**bot_kwargs):
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
    message_store = bot_kwargs.pop(
        "message_store",
        MessageStore(engine=engine),
    )
    bot = FanslyBot(
        client=client,
        persona_loader=persona_loader,
        note_repo=note_repo,
        creator_id="creator-a",
        state_repo=state_repo,
        message_store=message_store,
        **bot_kwargs,
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


def test_delivery_outcome_preserves_advanced_authority_attribution():
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        chat_responder=responder,
    )
    now = datetime.now(timezone.utc)
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="advanced-attribution-inbound",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=now,
    )
    decision = ConversationDecision(
        fan_state="engaged",
        state_summary="engaged",
        objective="maintain",
        tactic="direct_answer",
        open_thread=None,
        draft="advanced reply",
        critique=(),
        final_message="advanced reply",
        confidence=0.8,
    )
    bot.conversation_decision_repo.save(
        inbound_message_id=inbound.id,
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_kind="unread",
        decision=decision,
        model="deepseek-v4-flash",
        execution={
            "authority": "advanced",
            "brain_version": "brain2-v2",
            "variant": "advanced",
            "experiment_id": "canary-v2",
        },
    )
    TriggerOwnershipRepository(engine).assign(
        "creator-a",
        TriggerType.INBOUND_REPLY,
        TriggerOwner.BRAIN2,
        actor="test",
        reason="advanced authority test",
    )
    bot._prepare_message = MagicMock(
        return_value=OutboundMessage.text("advanced reply")
    )
    bot.client.send_message.return_value = SimpleNamespace(
        success=True,
        message_id="advanced-attribution-outbound",
    )

    claimed = bot.processing_repo.claim_next_inbound("creator-a")
    assert bot._process_claimed_inbound(claimed) is True

    outcome = _rows(engine, CONVERSATION_OUTCOMES)[0]
    assert outcome["brain_version"] == "brain2-v2"
    assert outcome["variant"] == "advanced"
    assert outcome["experiment_id"] == "canary-v2"


def test_pipeline_sorts_oldest_first_and_sends_every_message_once():
    engine, bot = _bot()
    chat = _chat(unread_count=3, last_message_id="message-3")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(3), _message(2), _message(1)],
        None,
    )
    bot._prepare_message = MagicMock(
        side_effect=lambda _chat, message, _messages, **_kwargs: (
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


def test_signed_webhook_path_bypasses_full_chat_reconciliation():
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        reply_delay_min_seconds=0,
        reply_delay_max_seconds=0,
    )
    event = OnlyFansApiFanslyMessage(
        platform_message_id="webhook-message-1",
        account_id="account-a",
        chat_id="chat-a",
        fan_id="fan-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )
    bot._prepare_message = MagicMock(return_value="fast reply")
    bot.client.send_message.return_value = SimpleNamespace(
        success=True,
        message_id="provider-reply-1",
    )

    assert bot.ingest_webhook_message(event) is True
    assert bot.ingest_webhook_message(event) is False
    assert bot.poll_and_process(
        reconcile=False,
        outreach=False,
    ) is True

    bot.client.list_chats_page.assert_not_called()
    bot.client.list_messages.assert_not_called()
    bot.client.send_message.assert_called_once_with(
        "chat-a",
        "fast reply",
    )
    assert len(_rows(engine, INBOUND_MESSAGES)) == 1


def test_conversation_generation_failure_is_retried_not_dropped():
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        processing_retry_base_seconds=5,
        processing_retry_max_seconds=60,
    )
    now = datetime.now(timezone.utc)
    bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=now,
        available_at=now,
    )
    bot._prepare_message = MagicMock(return_value=None)

    assert bot.drain_pending(max_messages=1) == 1

    row = _rows(engine, INBOUND_MESSAGES)[0]
    assert row["status"] == "pending"
    assert row["attempt_count"] == 1
    assert row["available_at"] > row["observed_at"]


def test_conversation_mode_combines_unread_window_into_one_reply():
    engine, bot = _bot(bot_mode=BotMode.CONVERSATION)
    chat = _chat(unread_count=3, last_message_id="message-3")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(3), _message(2), _message(1)],
        None,
    )
    bot._prepare_message = MagicMock(return_value="one reply")
    bot.client.send_message.return_value = SimpleNamespace(
        success=True,
        message_id="provider-reply-1",
    )

    assert bot.poll_and_process() is True

    bot._prepare_message.assert_called_once()
    prepared_message = bot._prepare_message.call_args.args[1]
    assert prepared_message.message_id == "message-3"
    assert prepared_message.content == (
        "inbound-1\ninbound-2\ninbound-3"
    )
    assert bot.client.send_message.call_args_list == [
        call("chat-a", "one reply")
    ]
    assert len(_rows(engine, INBOUND_MESSAGES)) == 1


def test_conversation_mode_persists_brain_decision_before_delivery():
    engine, bot = _bot(bot_mode=BotMode.CONVERSATION)
    responder = MagicMock()
    responder.enabled = True
    responder.model = "deepseek-v4-flash"
    responder.decide.return_value = ConversationDecision(
        fan_state="engaged",
        state_summary="Fan asked about the creator's day.",
        objective="answer",
        tactic="direct_answer",
        open_thread="today",
        draft="pretty good, how about you?",
        critique=("Make the question more specific",),
        final_message="pretty good babe, what was the best part of ur day?",
        confidence=0.82,
    )
    bot.chat_responder = responder
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot.client.send_message.return_value = SimpleNamespace(
        success=True,
        message_id="provider-reply-1",
    )

    assert bot.poll_and_process() is True

    inbound = _rows(engine, INBOUND_MESSAGES)[0]
    stored = bot.conversation_decision_repo.get(
        inbound["id"],
        creator_id="creator-a",
    )
    assert stored is not None
    assert stored.decision.objective == "answer"
    assert stored.decision.tactic == "direct_answer"
    assert stored.decision.critique == (
        "Make the question more specific",
    )
    assert stored.decision.final_message
    bot.client.send_message.assert_called_once()


def test_conversation_mode_never_ingests_changed_read_chat():
    engine, bot = _bot(bot_mode=BotMode.CONVERSATION)
    chat = _chat(unread_count=0, last_message_id="message-2")
    bot.client.list_chats_page.return_value = ([chat], None)

    assert bot.poll_and_process() is False

    bot.client.list_messages.assert_not_called()
    assert _rows(engine, INBOUND_MESSAGES) == []


def test_conversation_mode_skips_when_creator_already_replied():
    engine, bot = _bot(bot_mode=BotMode.CONVERSATION)
    chat = _chat(unread_count=1, last_message_id="message-2")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(2, fan=False), _message(1)],
        None,
    )

    assert bot.poll_and_process() is False

    assert _rows(engine, INBOUND_MESSAGES) == []


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


def test_recovery_chat_discovery_is_bounded_by_page_cap():
    _, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        recovery_chat_pages_per_run=2,
    )
    first = _chat(
        unread_count=0,
        last_message_id="message-1",
        chat_id="chat-1",
        fan_id="fan-1",
    )
    second = _chat(
        unread_count=0,
        last_message_id="message-2",
        chat_id="chat-2",
        fan_id="fan-2",
    )
    bot.client.list_chats_page.side_effect = [
        ([first], 100),
        ([second], 200),
        ([], None),
    ]

    bot.reconcile_provider()

    assert bot.client.list_chats_page.call_count == 2
    assert [
        item.kwargs["offset"]
        for item in bot.client.list_chats_page.call_args_list
    ] == [0, 100]


def test_recovery_message_read_is_bounded_and_advances_newest_head():
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        recovery_message_pages_per_chat=1,
    )
    chat = _chat(
        unread_count=2,
        last_message_id="message-2",
    )
    bot.client.list_messages.return_value = (
        [_message(2)],
        "older-page",
    )

    inserted, complete = bot._ingest_chat_messages(chat)

    assert inserted == 1
    assert complete is True
    bot.client.list_messages.assert_called_once_with(
        "chat-a",
        limit=100,
        cursor=None,
    )
    checkpoint, provider_cursor = (
        bot.state_repo.get_conversation_checkpoint(
            "creator-a",
            "chat-a",
        )
    )
    assert checkpoint == "message-2"
    assert provider_cursor is None
    assert len(_rows(engine, INBOUND_MESSAGES)) == 1


def test_first_scan_processes_only_the_provider_unread_window():
    engine, bot = _bot()
    chat = _chat(unread_count=2, last_message_id="message-5")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = (
        [_message(number) for number in range(5, 0, -1)],
        None,
    )
    bot._prepare_message = MagicMock(
        side_effect=lambda _chat, message, _messages, **_kwargs: (
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


def test_conversation_mode_blocks_ppv_even_when_provider_supports_it():
    engine, bot = _bot(bot_mode=BotMode.CONVERSATION)
    bot.client.capabilities = ProviderCapabilities(
        supports_paid_messages=True,
        supports_vault_albums=True,
        supports_attributed_purchases=True,
    )
    chat = _chat(unread_count=1, last_message_id="message-1")
    bot.client.list_chats_page.return_value = ([chat], None)
    bot.client.list_messages.return_value = ([_message(1)], None)
    bot._prepare_message = MagicMock(
        return_value=OutboundMessage.ppv(
            content="special",
            media_ids=("fansly_media_1",),
            price_millis=10_000,
            sequence_id=1,
            sequence_step_id=1,
        )
    )

    assert bot.poll_and_process() is True

    bot.client.send_ppv.assert_not_called()
    outbox = _rows(engine, OUTBOX_MESSAGES)[0]
    assert outbox["status"] == "blocked_unsupported"
    assert "text messages only" in outbox["last_error"]


def test_conversation_mode_quarantines_stale_pending_media():
    engine, bot = _bot()
    inbound, _ = bot.processing_repo.insert_inbound(
        creator_id="creator-a",
        platform_message_id="message-old",
        fan_id="fan-a",
        chat_id="chat-a",
        content="old",
        provider_created_at=datetime.now(timezone.utc),
    )
    bot.processing_repo.enqueue_outbox(
        inbound=inbound,
        message=OutboundMessage.media(
            "old media",
            ("fansly_media_1",),
        ),
    )

    count = bot.processing_repo.block_pending_non_text(
        "creator-a",
        "conversation mode permits text messages only",
    )

    assert count == 1
    assert _rows(engine, INBOUND_MESSAGES)[0]["status"] == "completed"
    outbox = _rows(engine, OUTBOX_MESSAGES)[0]
    assert outbox["status"] == "blocked_unsupported"


def test_online_presence_baselines_then_queues_one_transition():
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        enable_online_outreach=True,
        online_window_seconds=600,
        presence_poll_interval_seconds=0,
    )
    bot.client.capabilities = ProviderCapabilities(
        supports_user_presence=True,
    )
    bot.state_repo.ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
        display_name="Fan",
        username="fan",
    )
    now = datetime.now(timezone.utc)
    bot.client.get_user_presence.side_effect = [
        [
            UserPresence(
                "fan-a",
                "fan",
                "Fan",
                now.timestamp() * 1000,
                1,
            )
        ],
        [
            UserPresence(
                "fan-a",
                "fan",
                "Fan",
                (now - timedelta(hours=2)).timestamp() * 1000,
                0,
            )
        ],
        [
            UserPresence(
                "fan-a",
                "fan",
                "Fan",
                (now + timedelta(seconds=2)).timestamp() * 1000,
                1,
            )
        ],
        [
            UserPresence(
                "fan-a",
                "fan",
                "Fan",
                (now + timedelta(seconds=3)).timestamp() * 1000,
                1,
            )
        ],
    ]

    assert bot._poll_presence() is True
    assert _rows(engine, INBOUND_MESSAGES) == []
    assert bot._poll_presence() is False
    assert bot._poll_presence() is True
    rows = _rows(engine, INBOUND_MESSAGES)
    assert len(rows) == 1
    assert rows[0]["trigger_kind"] == "online"
    assert bot._poll_presence() is True
    assert len(_rows(engine, INBOUND_MESSAGES)) == 1


def test_zero_proactive_limits_mean_unlimited():
    _, bot = _bot()
    bot.state_repo.ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    now = datetime.now(timezone.utc)
    bot.presence_repo.observe(
        creator_id="creator-a",
        fan_id="fan-a",
        last_seen_at=now,
        provider_status_id=1,
        observed_at=now,
        online_window_seconds=600,
    )

    eligible, reason = bot.presence_repo.eligible_for_outreach(
        creator_id="creator-a",
        fan_id="fan-a",
        now=now,
        cooldown_hours=48,
        max_per_hour=0,
        max_per_day=0,
        max_per_fan_per_day=0,
    )

    assert eligible is True
    assert reason is None


def _seed_stalled_conversation(engine, bot):
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=48)
    bot.state_repo.ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    bot.message_store.save_message(
        "fan-a",
        "creator-a",
        "fan",
        "working late",
        "fan-message-1",
        chat_id="chat-a",
        created_at=old - timedelta(minutes=5),
    )
    bot.message_store.save_message(
        "fan-a",
        "creator-a",
        "creator",
        "hope it goes smoothly babe",
        "creator-message-1",
        chat_id="chat-a",
        created_at=old,
    )
    sync = CrmSyncRepository(engine)
    sync.discover_chat(
        creator_id="creator-a",
        chat_id="chat-a",
        fan_id="fan-a",
        provider_head_message_id="creator-message-1",
    )
    sync.complete_initial_page(
        creator_id="creator-a",
        chat_id="chat-a",
        provider_head_message_id="creator-message-1",
        backfill_cursor=None,
    )


def test_stalled_scan_queues_once_per_fan_response_episode():
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        enable_stalled_outreach=True,
        stalled_after_hours=24,
        stalled_scan_interval_seconds=0,
    )
    _seed_stalled_conversation(engine, bot)

    assert bot._poll_stalled_conversations() is True
    rows = _rows(engine, INBOUND_MESSAGES)
    assert len(rows) == 1
    assert rows[0]["trigger_kind"] == "stalled"
    assert rows[0]["content"] == "fan-message-1"

    claimed = bot.processing_repo.claim_next_inbound("creator-a")
    bot.processing_repo.complete_without_response(claimed.id)
    assert bot._poll_stalled_conversations() is False
    assert len(_rows(engine, INBOUND_MESSAGES)) == 1


def test_stalled_follow_up_is_cancelled_if_fan_replies_before_send():
    engine, bot = _bot(
        bot_mode=BotMode.CONVERSATION,
        enable_stalled_outreach=True,
        stalled_after_hours=24,
        stalled_scan_interval_seconds=0,
    )
    responder = MagicMock()
    responder.enabled = True
    bot.chat_responder = responder
    _seed_stalled_conversation(engine, bot)
    assert bot._poll_stalled_conversations() is True
    bot.message_store.save_message(
        "fan-a",
        "creator-a",
        "fan",
        "it went well",
        "fan-message-2",
        chat_id="chat-a",
        created_at=datetime.now(timezone.utc),
    )

    claimed = bot.processing_repo.claim_next_inbound("creator-a")
    assert bot._process_claimed_inbound(claimed) is True

    responder.decide.assert_not_called()
    bot.client.send_message.assert_not_called()
    assert _rows(engine, INBOUND_MESSAGES)[0]["status"] == "completed"


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
