"""Tests for FanslyBot on/off toggle."""
import pytest
from unittest.mock import MagicMock, patch
from src.bot import FanslyBot
from src.notes.repository import FanNoteRepository
from src.persona.loader import PersonaLoader
from src.fansly_client import FanslyApiClient, FanslyConfig


@pytest.fixture
def bot():
    """Create a FanslyBot with mocked dependencies for toggle testing."""
    client = MagicMock(spec=FanslyApiClient)
    client.account_id = "test"
    client.get_all_chats.return_value = []

    pl = MagicMock(spec=PersonaLoader)
    pl.load.return_value = MagicMock()
    pl.load.return_value.forbidden_phrases = []
    pl.load.return_value.pet_names = ["babe"]
    pl.load.return_value.common_typos = {}

    nr = FanNoteRepository("sqlite:///:memory:")
    nr.create_table()

    b = FanslyBot(client=client, persona_loader=pl, note_repo=nr)
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
    nr = FanNoteRepository("sqlite:///:memory:")
    nr.create_table()

    b = FanslyBot(client=client, persona_loader=pl, note_repo=nr)
    assert b.enabled == True


def test_poll_skips_when_disabled(bot):
    """poll_and_process should return early when bot is disabled."""
    bot.enabled = False
    bot.poll_and_process()
    bot.client.get_all_chats.assert_not_called()


def test_poll_calls_api_when_enabled(bot):
    """poll_and_process should call API when bot is enabled."""
    bot.enabled = True
    bot.poll_and_process()
    bot.client.get_all_chats.assert_called_once()


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


def test_poll_skips_list_messages_for_chats_with_no_unread(bot):
    """Chats with unread_count=0 should never trigger a list_messages call."""
    from src.fansly_client import ChatInfo
    bot.client.get_all_chats.return_value = [
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=0),
        ChatInfo(chat_id="c2", partner_account_id="p2", partner_username="u2",
                 partner_display_name="U2", unread_count=3),
    ]
    bot.client.list_messages.return_value = ([], None)

    bot.poll_and_process()

    bot.client.list_messages.assert_called_once_with("c2", limit=10)


def test_poll_returns_true_when_unread_found(bot):
    from src.fansly_client import ChatInfo
    bot.client.get_all_chats.return_value = [
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=2),
    ]
    bot.client.list_messages.return_value = ([], None)

    result = bot.poll_and_process()

    assert result is True


def test_poll_returns_false_when_no_unread_anywhere(bot):
    from src.fansly_client import ChatInfo
    bot.client.get_all_chats.return_value = [
        ChatInfo(chat_id="c1", partner_account_id="p1", partner_username="u1",
                 partner_display_name="U1", unread_count=0),
    ]

    result = bot.poll_and_process()

    assert result is False


def test_poll_returns_false_when_disabled(bot):
    bot.enabled = False
    result = bot.poll_and_process()
    assert result is False