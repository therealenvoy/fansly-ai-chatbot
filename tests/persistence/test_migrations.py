from io import StringIO
from pathlib import Path

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
    assert {
        "fan_notes",
        "fan_messages",
        "ppv_sequences",
        "ppv_sequence_steps",
        "ppv_fan_progress",
    } <= tables
    assert "alembic_version" in tables
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, metadata) == []


def test_upgrade_is_idempotent_and_downgrade_preserves_adopted_tables(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"

    upgrade_database(database_url)
    upgrade_database(database_url)
    command.downgrade(alembic_config(database_url), "base")

    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "fan_notes",
        "fan_messages",
        "ppv_sequences",
        "ppv_sequence_steps",
        "ppv_fan_progress",
    } <= tables
    assert {
        "creators",
        "fans",
        "conversations",
        "fan_runtime_states",
        "inbound_messages",
        "outbox_messages",
        "purchase_events",
        "provider_wallet_transactions",
    }.isdisjoint(tables)


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


def test_upgrade_adopts_legacy_fan_notes_without_losing_data(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE fan_notes ("
                "fan_id VARCHAR NOT NULL, "
                "creator_id VARCHAR NOT NULL, "
                "display_name VARCHAR, "
                "preferences TEXT, "
                "occupation VARCHAR, "
                "total_spent FLOAT, "
                "purchase_count INTEGER, "
                "last_purchase_at DATETIME, "
                "emotional_triggers TEXT, "
                "hard_limits TEXT, "
                "notes TEXT, "
                "first_contact_at DATETIME, "
                "relationship_stage VARCHAR, "
                "PRIMARY KEY (fan_id, creator_id)"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO fan_notes "
                "(fan_id, creator_id, display_name, notes) "
                "VALUES ('fan-a', 'creator-a', 'Existing Fan', 'keep me')"
            )
        )

    upgrade_database(database_url)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("fan_notes")
    }
    assert "facts" in columns
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT display_name, notes, facts "
                "FROM fan_notes WHERE fan_id = 'fan-a'"
            )
        ).one()
    assert row.display_name == "Existing Fan"
    assert row.notes == "keep me"
    assert row.facts == "[]"


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
    assert "ALTER TABLE outbox_messages ADD COLUMN message_kind" in sql
    assert "CREATE TABLE provider_wallet_transactions" in sql
    assert "CREATE TABLE purchase_events" in sql
    assert "CREATE TABLE fan_notes" in sql
    assert "CREATE TABLE fan_messages" in sql
    assert "CREATE TABLE ppv_sequences" in sql
    assert "CREATE TABLE ppv_sequence_steps" in sql
    assert "CREATE TABLE ppv_fan_progress" in sql
    assert "CREATE TABLE script_templates" in sql
    assert "CREATE TABLE media_assets" in sql
    assert "provider_purchase_ref" in sql
    assert "CREATE TABLE crm_chat_sync" in sql
    assert "CREATE TABLE fan_presence" in sql
    assert "CREATE TABLE conversation_decisions" in sql
    assert "trigger_kind" in sql
    assert "ALTER TABLE fans ADD COLUMN username" in sql
    assert "ALTER TABLE fan_messages ADD COLUMN attachments" in sql
    assert "JSON NOT NULL" in sql


def test_application_startup_does_not_create_schema():
    root = Path(__file__).resolve().parents[2]
    main_source = (root / "src" / "main.py").read_text(
        encoding="utf-8"
    )
    dashboard_source = (
        root / "src" / "web" / "dashboard.py"
    ).read_text(encoding="utf-8")

    assert ".create_table(" not in main_source
    assert ".create_tables(" not in main_source
    assert "store.create_table()" not in dashboard_source
