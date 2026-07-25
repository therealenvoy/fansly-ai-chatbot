from io import StringIO

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from src.persistence.migrations import alembic_config, upgrade_database
from src.persistence.schema import metadata
from src.settings.store import SettingsStore


def test_upgrade_creates_exact_durable_schema(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"

    upgrade_database(database_url)

    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert set(metadata.tables).issubset(tables)
    assert "alembic_version" in tables
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, metadata) == []


def test_upgrade_is_idempotent_and_downgrade_removes_durable_tables(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"

    upgrade_database(database_url)
    upgrade_database(database_url)
    command.downgrade(alembic_config(database_url), "base")

    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert set(metadata.tables).isdisjoint(tables)


def test_upgrade_preserves_legacy_global_settings(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE bot_settings "
                "(key VARCHAR PRIMARY KEY, value TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bot_settings (key, value) "
                "VALUES ('bot_enabled', 'false')"
            )
        )

    upgrade_database(database_url)

    creator_store = SettingsStore(
        database_url,
        creator_id="creator-a",
    )
    assert creator_store.get("bot_enabled") == "false"


def test_postgresql_offline_upgrade_compiles_without_sqlite_types():
    output = StringIO()
    config = alembic_config(
        "postgresql://user:password@example.invalid/database"
    )
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE inbound_messages" in sql
    assert "BIGSERIAL" in sql
    assert "CREATE TABLE fan_runtime_states" in sql
    assert "JSON NOT NULL" in sql
