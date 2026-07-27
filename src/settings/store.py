"""Creator-scoped settings persisted through the shared database engine."""

from __future__ import annotations

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.persistence.database import create_database_engine
from src.persistence.schema import CREATORS, CREATOR_SETTINGS, metadata, utcnow


BOT_SETTINGS_TABLE = CREATOR_SETTINGS


class SettingsStore:
    """Creator-scoped key-value settings store.

    ``global`` remains the default creator for backwards-compatible local
    callers, while the application always supplies its real creator id.
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        engine=None,
        creator_id: str = "global",
    ):
        if engine is None and db_url is None:
            raise ValueError("db_url or engine is required")
        self.engine = engine or create_database_engine(db_url)
        self.creator_id = creator_id

    def create_table(self):
        metadata.create_all(
            self.engine,
            tables=[CREATORS, CREATOR_SETTINGS],
            checkfirst=True,
        )

    def get(self, key: str, default=None):
        value = self._get_for_creator(self.creator_id, key)
        if value is None and self.creator_id != "global":
            value = self._get_for_creator("global", key)
        return value if value is not None else default

    def get_scoped(self, key: str, default=None):
        """Read only this creator's value without global fallback."""
        value = self._get_for_creator(self.creator_id, key)
        return value if value is not None else default

    def set(self, key: str, value: str):
        self.set_many({key: value})

    def set_many(self, values: dict[str, str]):
        """Persist several creator settings in one transaction."""
        if not values:
            return
        now = utcnow()
        with self.engine.begin() as conn:
            self._ensure_creator(self.creator_id, connection=conn)
            for key, value in values.items():
                stmt = self._insert(CREATOR_SETTINGS).values(
                    creator_id=self.creator_id,
                    key=key,
                    value=str(value),
                    updated_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["creator_id", "key"],
                    set_={"value": str(value), "updated_at": now},
                )
                conn.execute(stmt)

    def delete(self, key: str):
        stmt = delete(CREATOR_SETTINGS).where(
            and_(
                CREATOR_SETTINGS.c.creator_id == self.creator_id,
                CREATOR_SETTINGS.c.key == key,
            )
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def _get_for_creator(self, creator_id: str, key: str):
        stmt = select(CREATOR_SETTINGS.c.value).where(
            and_(
                CREATOR_SETTINGS.c.creator_id == creator_id,
                CREATOR_SETTINGS.c.key == key,
            )
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar_one_or_none()

    def _ensure_creator(self, creator_id: str, *, connection=None):
        now = utcnow()
        stmt = self._insert(CREATORS).values(
            id=creator_id,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"updated_at": now},
        )
        if connection is not None:
            connection.execute(stmt)
            return
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
