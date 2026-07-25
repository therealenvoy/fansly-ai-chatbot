"""Tests for SettingsStore — key-value persistence."""
import pytest
import os
from src.settings.store import SettingsStore, BOT_SETTINGS_TABLE


@pytest.fixture
def store():
    """In-memory SQLite SettingsStore for testing."""
    s = SettingsStore("sqlite:///:memory:")
    s.create_table()
    return s


def test_get_default_on_empty_key(store):
    """get() should return default when key doesn't exist."""
    assert store.get("bot_enabled", True) == True


def test_set_and_get_string(store):
    """set() then get() should return the same value."""
    store.set("bot_enabled", "false")
    assert store.get("bot_enabled") == "false"


def test_set_and_get_boolean(store):
    """set() with boolean should store as string."""
    store.set("bot_enabled", False)
    assert store.get("bot_enabled", True) == "False"


def test_set_overwrites(store):
    """set() should overwrite existing value."""
    store.set("key", "v1")
    store.set("key", "v2")
    assert store.get("key") == "v2"


def test_get_nonexistent_returns_default(store):
    """get() should return default for nonexistent keys."""
    assert store.get("nah", 42) == 42


def test_persists_across_instances():
    """Values should survive store re-initialization."""
    db_path = "/tmp/test_settings_persist.db"
    try:
        s1 = SettingsStore(f"sqlite:///{db_path}")
        s1.create_table()
        s1.set("bot_enabled", "false")

        s2 = SettingsStore(f"sqlite:///{db_path}")
        s2.create_table()
        assert s2.get("bot_enabled") == "false"
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)