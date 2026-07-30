"""Creator-scoped durable cache for credit-bearing provider reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .persistence.schema import PROVIDER_READ_CACHE


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProviderReadSnapshot:
    payload: dict[str, Any]
    fetched_at: datetime
    expires_at: datetime
    stale_until: datetime

    def is_fresh(self, now: datetime) -> bool:
        return _utc(now) < _utc(self.expires_at)

    def is_usable_stale(self, now: datetime) -> bool:
        return _utc(now) < _utc(self.stale_until)

    def age_seconds(self, now: datetime) -> int:
        return max(
            0,
            int((_utc(now) - _utc(self.fetched_at)).total_seconds()),
        )


class ProviderReadCache:
    """Small JSON snapshot cache shared across Railway restarts."""

    def __init__(self, engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id

    def _insert(self):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(PROVIDER_READ_CACHE)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(PROVIDER_READ_CACHE)
        return insert(PROVIDER_READ_CACHE)

    def get(
        self,
        namespace: str,
        cache_key: str,
    ) -> ProviderReadSnapshot | None:
        statement = select(
            PROVIDER_READ_CACHE.c.payload,
            PROVIDER_READ_CACHE.c.fetched_at,
            PROVIDER_READ_CACHE.c.expires_at,
            PROVIDER_READ_CACHE.c.stale_until,
        ).where(
            PROVIDER_READ_CACHE.c.creator_id == self.creator_id,
            PROVIDER_READ_CACHE.c.namespace == namespace,
            PROVIDER_READ_CACHE.c.cache_key == cache_key,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None or not isinstance(row["payload"], dict):
            return None
        return ProviderReadSnapshot(
            payload=dict(row["payload"]),
            fetched_at=_utc(row["fetched_at"]),
            expires_at=_utc(row["expires_at"]),
            stale_until=_utc(row["stale_until"]),
        )

    def put(
        self,
        namespace: str,
        cache_key: str,
        payload: dict[str, Any],
        *,
        fetched_at: datetime,
        ttl: timedelta,
        stale_ttl: timedelta,
    ) -> None:
        fetched = _utc(fetched_at)
        values = {
            "creator_id": self.creator_id,
            "namespace": namespace,
            "cache_key": cache_key,
            "payload": payload,
            "fetched_at": fetched,
            "expires_at": fetched + ttl,
            "stale_until": fetched + stale_ttl,
            "updated_at": fetched,
        }
        statement = self._insert().values(**values)
        if hasattr(statement, "on_conflict_do_update"):
            statement = statement.on_conflict_do_update(
                index_elements=[
                    "creator_id",
                    "namespace",
                    "cache_key",
                ],
                set_={
                    key: value
                    for key, value in values.items()
                    if key not in {
                        "creator_id",
                        "namespace",
                        "cache_key",
                    }
                },
            )
        with self.engine.begin() as connection:
            connection.execute(statement)

    def invalidate(
        self,
        namespace: str,
        cache_key: str | None = None,
    ) -> None:
        statement = delete(PROVIDER_READ_CACHE).where(
            PROVIDER_READ_CACHE.c.creator_id == self.creator_id,
            PROVIDER_READ_CACHE.c.namespace == namespace,
        )
        if cache_key is not None:
            statement = statement.where(
                PROVIDER_READ_CACHE.c.cache_key == cache_key
            )
        with self.engine.begin() as connection:
            connection.execute(statement)
