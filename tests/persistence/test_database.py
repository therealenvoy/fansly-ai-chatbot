import pytest

from src.memory.store import MessageStore
from src.notes.repository import FanNoteRepository
from src.persistence.database import (
    create_database_engine,
    normalize_database_url,
)
from src.sequences.repository import SequenceRepository
from src.settings.store import SettingsStore


def test_normalizes_railway_postgres_urls():
    assert (
        normalize_database_url("postgres://user:pass@host/db")
        == "postgresql+psycopg2://user:pass@host/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host/db")
        == "postgresql+psycopg2://user:pass@host/db"
    )


def test_sqlite_is_available_for_local_tests():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    assert engine.dialect.name == "sqlite"


def test_sqlite_fails_closed_in_production():
    with pytest.raises(RuntimeError, match="not allowed in production"):
        create_database_engine(
            "sqlite:///data/bot.db",
            environment={"RAILWAY_ENVIRONMENT_NAME": "production"},
        )


def test_database_url_is_required():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_database_engine("", environment={"APP_ENV": "test"})


def test_all_repositories_can_share_one_engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )

    repositories = [
        FanNoteRepository(engine=engine),
        MessageStore(engine=engine),
        SequenceRepository(engine=engine),
        SettingsStore(engine=engine, creator_id="creator-a"),
    ]

    assert all(repository.engine is engine for repository in repositories)
