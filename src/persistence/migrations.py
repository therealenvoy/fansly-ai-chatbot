"""Programmatic Alembic migration entry point."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from src.conversation.authority import AUTHORITY_MAX_LENGTH
from .database import normalize_database_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(PROJECT_ROOT / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        normalize_database_url(database_url).replace("%", "%%"),
    )
    return config


def upgrade_database(database_url: str, *, engine=None) -> None:
    config = alembic_config(database_url)
    config.attributes["configure_logger"] = False
    if engine is None:
        command.upgrade(config, "head")
        return
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    assert_runtime_schema_compatible(engine)


def assert_runtime_schema_compatible(engine) -> None:
    """Fail startup before accepting traffic with an incompatible schema."""
    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns(
            "conversation_decisions"
        )
    }
    authority = columns.get("authority")
    actual_length = getattr(
        (authority or {}).get("type"),
        "length",
        None,
    )
    if actual_length is None or int(actual_length) < AUTHORITY_MAX_LENGTH:
        raise RuntimeError("conversation_decision_authority_schema_incompatible")
