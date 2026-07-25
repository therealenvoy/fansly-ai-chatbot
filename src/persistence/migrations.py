"""Programmatic Alembic migration entry point."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

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
