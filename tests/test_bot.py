"""Tests for FanslyBot on/off toggle."""
import pytest
from unittest.mock import MagicMock, patch
from src.bot import FanslyBot
from src.notes.repository import FanNoteRepository
from src.persona.loader import PersonaLoader
from src.fansly_client import FanslyClient, FanslyConfig


@pytest.fixture
def bot():
    """Create a FanslyBot with mocked dependencies for toggle testing."""
    client = MagicMock(spec=FanslyClient)
    client.config = FanslyConfig(api_key="test", account_id="test")
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
    client = MagicMock(spec=FanslyClient)
    client.config = FanslyConfig(api_key="test", account_id="test")
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