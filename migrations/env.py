from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.persistence.database import normalize_database_url
from src.persistence.schema import metadata


config = context.config
if (
    config.config_file_name is not None
    and config.attributes.get("configure_logger", True)
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    return normalize_database_url(configured)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided_connection = config.attributes.get("connection")
    if provided_connection is not None:
        context.configure(
            connection=provided_connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
