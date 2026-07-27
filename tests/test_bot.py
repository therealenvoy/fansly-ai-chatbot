"""Tests for FanslyBot on/off toggle."""
import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace
from src.bot import FanslyBot, LaunchGuardError
from src.conversation.mode import BotMode
from src.notes.repository import FanNoteRepository
from src.notes.models import FanNote
from src.persona.loader import PersonaLoader
from src.fansly_client import (
    FanslyApiClient,
    MessageInfo,
    ProviderCapabilities,
)
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository


def test_fan_memory_includes_durable_profile_without_purchase_labels():
    note = FanNote(
        fan_id="fan-a",
        creator_id="creator-a",
        occupation="nurse",
        preferences=["likes late-night chats"],
        emotional_triggers=["responds well to humor"],
        hard_limits=["no pet names"],
        facts=["has a dog named Max"],
        notes="Keep replies calm.",
        relationship_stage="regular",
        total_spent=900,
    )

    memory = FanslyBot._fan_memory(note)

    assert "Relationship stage: regular" in memory
    assert "Occupation: nurse" in memory
    assert "Preference: likes late-night chats" in memory
    assert "Emotional cue: responds well to humor" in memory
    assert "Hard limit: no pet names" in memory
    assert "Known fact: has a dog named Max" in memory
    assert "Operator note: Keep replies calm." in memory
    assert all("spent" not in item.lower() for item in memory)


@pytest.fixture
def bot():
    """Create a FanslyBot with mocked dependencies for toggle testing."""
    client = MagicMock(spec=FanslyApiClient)
    client.account_id = "test"
    client.list_chats_page.return_value = ([], None)
    client.capabilities = ProviderCapabilities(
        supports_free_media_messages=True,
        supports_paid_messages=True,
        supports_attributed_purchases=True,
        supports_vault_albums=True,
    )

    pl = MagicMock(spec=PersonaLoader)
    pl.load.return_value = MagicMock()
    pl.load.return_value.forbidden_phrases = []
    pl.load.return_value.pet_names = ["babe"]
    pl.load.return_value.common_typos = {}

    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    nr = FanNoteRepository(engine=engine)
    nr.create_table()

    b = FanslyBot(
        client=client,
        persona_loader=pl,
        note_repo=nr,
        state_repo=ConversationStateRepository(engine),
    )
    # Reset enabled after __init__ so we test the default, not our override
    b.enabled = True
    return b


def test_bot_enabled_by_default():
    """Bot should be enabled on init."""
    client = MagicMock(spec=FanslyApiClient)
    client.account_id = "test"
    pl = MagicMock(spec=PersonaLoader)
    pl.load.return_value = MagicMock()
    pl.load.return_value.forbidden_phrases = []
    pl.load.return_value.pet_names = ["babe"]
    pl.load.return_value.common_typos = {}
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    nr = FanNoteRepository(engine=engine)
    nr.create_table()

    b = FanslyBot(
        client=client,
        persona_loader=pl,
        note_repo=nr,
        state_repo=ConversationStateRepository(engine),
    )
    assert b.enabled == True


def test_poll_skips_when_disabled(bot):
    """poll_and_process should return early when bot is disabled."""
    bot.enabled = False
    bot.poll_and_process()
    bot.client.list_chats_page.assert_not_called()


def test_disabled_conversation_bot_observes_presence_without_queueing(bot):
    bot.bot_mode = BotMode.CONVERSATION
    bot.enable_online_outreach = True
    bot.enabled = False
    bot._poll_presence = MagicMock(return_value=True)

    assert bot.poll_and_process() is False

    bot._poll_presence.assert_called_once_with(queue_outreach=False)
    bot.client.list_chats_page.assert_not_called()


def test_poll_calls_api_when_enabled(bot):
    """poll_and_process should call API when bot is enabled."""
    bot.enabled = True
    bot.poll_and_process()
    bot.client.list_chats_page.assert_called_once()


def test_toggle_off(bot):
    """toggle() should set enabled=False when currently enabled."""
    bot.enabled = True
    result = bot.toggle(force=False)
    assert bot.enabled == False
    assert result == False


def test_toggle_on(bot):
    """toggle() should set enabled=True when currently disabled."""
    bot.enabled = False
    result = bot.toggle(force=None)
    assert bot.enabled == True
    assert result == True


def test_toggle_flip(bot):
    """toggle() without force should flip the state."""
    bot.enabled = True
    bot.toggle()
    assert bot.enabled == False
    bot.toggle()
    assert bot.enabled == True


def test_toggle_force_true(bot):
    """toggle(force=True) should enable regardless of current state."""
    bot.enabled = False
    bot.toggle(force=True)
    assert bot.enabled == True


def test_toggle_force_false(bot):
    """toggle(force=False) should disable regardless of current state."""
    bot.enabled = True
    bot.toggle(force=False)
    assert bot.enabled == False


def test_controlled_launch_rejects_enable_without_allowlist(bot):
    bot.require_fan_allowlist = True
    bot.allowed_fan_ids = frozenset()
    bot.enabled = False

    with pytest.raises(LaunchGuardError, match="FAN_ALLOWLIST"):
        bot.toggle(force=True)

    assert bot.enabled is False


def test_conversation_mode_launch_requires_llm_but_not_ppv(bot):
    bot.bot_mode = BotMode.CONVERSATION
    bot.chat_responder = SimpleNamespace(enabled=True)
    bot.enable_unread_replies = True
    bot.enable_online_outreach = False
    bot.client.capabilities = ProviderCapabilities()
    bot.enabled = False

    assert bot.launch_ready is True
    assert bot.toggle(force=True) is True


def test_conversation_mode_online_launch_requires_presence(bot):
    bot.bot_mode = BotMode.CONVERSATION
    bot.chat_responder = SimpleNamespace(enabled=True)
    bot.enable_unread_replies = True
    bot.enable_online_outreach = True
    bot.client.capabilities = ProviderCapabilities()

    assert bot.launch_ready is False
    assert "recent fan activity" in bot.launch_block_reason


def test_conversation_mode_launch_requires_llm(bot):
    bot.bot_mode = BotMode.CONVERSATION
    bot.chat_responder = SimpleNamespace(enabled=False)
    bot.enable_online_outreach = False

    assert bot.launch_ready is False
    assert "DEEPSEEK_API_KEY" in bot.launch_block_reason


def test_controlled_launch_filters_durable_chats(bot):
    from src.fansly_client import ChatInfo

    bot.require_fan_allowlist = True
    bot.allowed_fan_ids = frozenset({"pilot"})
    bot.client.list_chats_page.return_value = ([
        ChatInfo(
            chat_id="allowed",
            partner_account_id="pilot",
            partner_username="pilot",
            partner_display_name="Pilot",
            unread_count=1,
        ),
        ChatInfo(
            chat_id="blocked",
            partner_account_id="not-pilot",
            partner_username="other",
            partner_display_name="Other",
            unread_count=1,
        ),
    ], None)
    bot.client.list_messages.return_value = ([], None)

    bot.poll_and_process()

    bot.client.list_messages.assert_called_once_with(
        "allowed",
        limit=100,
        cursor=None,
    )


def test_poll_skips_list_messages_for_chats_with_no_unread(bot):
    """Chats with unread_count=0 should never trigger a list_messages call."""
    from src.fansly_client import ChatInfo
    bot.client.list_chats_page.return_value = ([
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=0),
        ChatInfo(chat_id="c2", partner_account_id="p2", partner_username="u2",
                 partner_display_name="U2", unread_count=3),
    ], None)
    bot.client.list_messages.return_value = ([], None)

    bot.poll_and_process()

    bot.client.list_messages.assert_called_once_with(
        "c2",
        limit=100,
        cursor=None,
    )


def test_poll_returns_true_when_unread_found(bot):
    from src.fansly_client import ChatInfo
    bot.client.list_chats_page.return_value = ([
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=2),
    ], None)
    bot.client.list_messages.return_value = ([
        MessageInfo(
            message_id="message-1",
            content="hello",
            sender_id="p1",
            created_at=1,
            is_from_fan=True,
        )
    ], None)
    bot._prepare_message = MagicMock(return_value=None)

    result = bot.poll_and_process()

    assert result is True


def test_poll_returns_false_when_no_unread_anywhere(bot):
    from src.fansly_client import ChatInfo
    bot.client.list_chats_page.return_value = ([
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=0),
    ], None)

    result = bot.poll_and_process()

    assert result is False


def test_poll_returns_false_when_disabled(bot):
    bot.enabled = False
    result = bot.poll_and_process()
    assert result is False
