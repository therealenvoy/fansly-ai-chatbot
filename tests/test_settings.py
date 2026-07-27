"""Tests for SettingsStore — key-value persistence."""
import pytest
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

def test_set_many_is_atomic_and_delete_removes_value(store):
    store.set_many({"first": "one", "second": "two"})

    assert store.get("first") == "one"
    assert store.get("second") == "two"

    store.delete("first")

    assert store.get("first") is None
    assert store.get("second") == "two"


def test_get_nonexistent_returns_default(store):
    """get() should return default for nonexistent keys."""
    assert store.get("nah", 42) == 42


def test_persists_across_instances(tmp_path):
    """Values should survive store re-initialization."""
    db_path = tmp_path / "test_settings_persist.db"

    s1 = SettingsStore(f"sqlite:///{db_path}")
    s1.create_table()
    s1.set("bot_enabled", "false")

    s2 = SettingsStore(f"sqlite:///{db_path}")
    s2.create_table()
    assert s2.get("bot_enabled") == "false"


def test_settings_are_scoped_per_creator(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'creator_settings.db'}"
    first = SettingsStore(db_url, creator_id="creator-a")
    second = SettingsStore(db_url, creator_id="creator-b")
    first.create_table()

    first.set("bot_enabled", "true")
    second.set("bot_enabled", "false")

    assert first.get("bot_enabled") == "true"
    assert second.get("bot_enabled") == "false"


def test_exact_scoped_read_does_not_inherit_global_value(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'scoped-settings.db'}"
    global_store = SettingsStore(db_url, creator_id="global")
    creator_store = SettingsStore(db_url, creator_id="creator-a")
    global_store.create_table()
    global_store.set("shared_default", "global-value")

    assert creator_store.get("shared_default") == "global-value"
    assert creator_store.get_scoped("shared_default") is None
