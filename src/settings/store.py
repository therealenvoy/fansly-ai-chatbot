"""SettingsStore — key-value persistence for bot settings.

Uses SQLAlchemy Core with a simple key-value table.
Values are stored as text; callers handle type conversion.
"""
from sqlalchemy import create_engine, MetaData, Table, Column, String, Text, select


BOT_SETTINGS_TABLE = Table(
    "bot_settings",
    MetaData(),
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=True),
)


class SettingsStore:
    """Simple key-value store for bot settings, persisted to SQLite/Postgres."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    def create_table(self):
        """Create the bot_settings table if it doesn't exist."""
        BOT_SETTINGS_TABLE.create(self.engine, checkfirst=True)

    def get(self, key: str, default=None):
        """Get a value by key. Returns default if key doesn't exist."""
        with self.engine.connect() as conn:
            result = conn.execute(
                select(BOT_SETTINGS_TABLE.c.value).where(
                    BOT_SETTINGS_TABLE.c.key == key
                )
            ).scalar_one_or_none()
        return result if result is not None else default

    def set(self, key: str, value: str):
        """Set a value by key. Creates or overwrites."""
        from sqlalchemy import select as _select
        with self.engine.begin() as conn:
            # Check if key exists
            existing = conn.execute(
                _select(BOT_SETTINGS_TABLE.c.key).where(
                    BOT_SETTINGS_TABLE.c.key == key
                )
            ).scalar_one_or_none()
            if existing:
                conn.execute(
                    BOT_SETTINGS_TABLE.update()
                    .where(BOT_SETTINGS_TABLE.c.key == key)
                    .values(value=str(value))
                )
            else:
                conn.execute(
                    BOT_SETTINGS_TABLE.insert().values(
                        key=key, value=str(value)
                    )
                )