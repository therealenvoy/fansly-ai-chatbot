"""Durable state for incremental CRM conversation-history synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .schema import CRM_CHAT_SYNC, FAN_MESSAGES, utcnow


@dataclass(frozen=True)
class CrmChatSyncState:
    creator_id: str
    chat_id: str
    fan_id: str
    provider_head_message_id: str | None
    stored_head_message_id: str | None
    incremental_cursor: str | None
    backfill_cursor: str | None
    history_complete: bool
    last_synced_at: datetime | None
    last_error: str | None

    @property
    def has_new_head(self) -> bool:
        return self.provider_head_message_id != self.stored_head_message_id


class CrmSyncRepository:
    """Track discovery, recent-message sync, and resumable deep backfill."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def discover_chat(
        self,
        *,
        creator_id: str,
        chat_id: str,
        fan_id: str,
        provider_head_message_id: str | None,
    ) -> None:
        self.discover_chats(
            creator_id=creator_id,
            chats=[
                {
                    "chat_id": chat_id,
                    "fan_id": fan_id,
                    "provider_head_message_id": provider_head_message_id,
                }
            ],
        )

    def discover_chats(
        self,
        *,
        creator_id: str,
        chats: list[dict],
    ) -> None:
        """Upsert one provider chat page in a single transaction."""
        if not chats:
            return
        now = utcnow()
        unique_chats: dict[str, dict] = {}
        for chat in chats:
            chat_id = str(chat["chat_id"])
            unique_chats[chat_id] = {
                "creator_id": creator_id,
                "chat_id": chat_id,
                "fan_id": str(chat["fan_id"]),
                "provider_head_message_id": chat.get(
                    "provider_head_message_id"
                ),
                "stored_head_message_id": None,
                "incremental_cursor": None,
                "backfill_cursor": None,
                "history_complete": False,
                "last_synced_at": None,
                "last_error": None,
                "created_at": now,
                "updated_at": now,
            }
        stmt = self._insert(CRM_CHAT_SYNC).values(
            list(unique_chats.values())
        )
        excluded = stmt.excluded
        head_changed = self._different(
            CRM_CHAT_SYNC.c.provider_head_message_id,
            excluded.provider_head_message_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["creator_id", "chat_id"],
            set_={
                "fan_id": excluded.fan_id,
                "provider_head_message_id": (
                    excluded.provider_head_message_id
                ),
                "incremental_cursor": case(
                    (head_changed, None),
                    else_=CRM_CHAT_SYNC.c.incremental_cursor,
                ),
                "last_error": case(
                    (head_changed, None),
                    else_=CRM_CHAT_SYNC.c.last_error,
                ),
                "updated_at": now,
            },
        )
        with self.engine.begin() as connection:
            connection.execute(stmt)

    def pending(
        self,
        creator_id: str,
        *,
        limit: int,
    ) -> list[CrmChatSyncState]:
        has_new_head = self._different(
            CRM_CHAT_SYNC.c.provider_head_message_id,
            CRM_CHAT_SYNC.c.stored_head_message_id,
        )
        statement = (
            select(CRM_CHAT_SYNC)
            .where(
                and_(
                    CRM_CHAT_SYNC.c.creator_id == creator_id,
                    or_(
                        has_new_head,
                        CRM_CHAT_SYNC.c.history_complete.is_(False),
                    ),
                )
            )
            .order_by(
                case((has_new_head, 0), else_=1),
                case(
                    (CRM_CHAT_SYNC.c.last_synced_at.is_(None), 0),
                    else_=1,
                ),
                CRM_CHAT_SYNC.c.last_synced_at.asc(),
                CRM_CHAT_SYNC.c.updated_at.desc(),
                CRM_CHAT_SYNC.c.chat_id.asc(),
            )
            .limit(max(0, limit))
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._state(row) for row in rows]

    def for_fan(
        self,
        creator_id: str,
        fan_id: str,
    ) -> list[CrmChatSyncState]:
        """Return only this creator's provider chats for one fan."""
        statement = (
            select(CRM_CHAT_SYNC)
            .where(
                and_(
                    CRM_CHAT_SYNC.c.creator_id == creator_id,
                    CRM_CHAT_SYNC.c.fan_id == fan_id,
                )
            )
            .order_by(CRM_CHAT_SYNC.c.chat_id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._state(row) for row in rows]

    def remaining(self, creator_id: str) -> int:
        has_new_head = self._different(
            CRM_CHAT_SYNC.c.provider_head_message_id,
            CRM_CHAT_SYNC.c.stored_head_message_id,
        )
        statement = select(func.count()).select_from(
            CRM_CHAT_SYNC
        ).where(
            and_(
                CRM_CHAT_SYNC.c.creator_id == creator_id,
                or_(
                    has_new_head,
                    CRM_CHAT_SYNC.c.history_complete.is_(False),
                ),
            )
        )
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one() or 0)

    def summary(self, creator_id: str) -> dict[str, int]:
        has_new_head = self._different(
            CRM_CHAT_SYNC.c.provider_head_message_id,
            CRM_CHAT_SYNC.c.stored_head_message_id,
        )
        pending = or_(
            has_new_head,
            CRM_CHAT_SYNC.c.history_complete.is_(False),
        )
        with self.engine.connect() as connection:
            discovered = int(
                connection.execute(
                    select(func.count())
                    .select_from(CRM_CHAT_SYNC)
                    .where(CRM_CHAT_SYNC.c.creator_id == creator_id)
                ).scalar_one()
                or 0
            )
            pending_chats = int(
                connection.execute(
                    select(func.count())
                    .select_from(CRM_CHAT_SYNC)
                    .where(
                        and_(
                            CRM_CHAT_SYNC.c.creator_id == creator_id,
                            pending,
                        )
                    )
                ).scalar_one()
                or 0
            )
            failed_chats = int(
                connection.execute(
                    select(func.count())
                    .select_from(CRM_CHAT_SYNC)
                    .where(
                        and_(
                            CRM_CHAT_SYNC.c.creator_id == creator_id,
                            CRM_CHAT_SYNC.c.last_error.is_not(None),
                        )
                    )
                ).scalar_one()
                or 0
            )
            stored_messages = int(
                connection.execute(
                    select(func.count())
                    .select_from(FAN_MESSAGES)
                    .where(FAN_MESSAGES.c.creator_id == creator_id)
                ).scalar_one()
                or 0
            )
        return {
            "discovered_chats": discovered,
            "complete_chats": max(discovered - pending_chats, 0),
            "pending_chats": pending_chats,
            "failed_chats": failed_chats,
            "stored_messages": stored_messages,
        }

    def complete_initial_page(
        self,
        *,
        creator_id: str,
        chat_id: str,
        provider_head_message_id: str | None,
        backfill_cursor: str | None,
    ) -> None:
        self._update(
            creator_id,
            chat_id,
            stored_head_message_id=provider_head_message_id,
            incremental_cursor=None,
            backfill_cursor=backfill_cursor,
            history_complete=backfill_cursor is None,
            last_synced_at=utcnow(),
            last_error=None,
        )

    def continue_incremental(
        self,
        *,
        creator_id: str,
        chat_id: str,
        cursor: str,
    ) -> None:
        self._update(
            creator_id,
            chat_id,
            incremental_cursor=cursor,
            last_synced_at=utcnow(),
            last_error=None,
        )

    def complete_incremental(
        self,
        *,
        creator_id: str,
        chat_id: str,
        provider_head_message_id: str | None,
    ) -> None:
        self._update(
            creator_id,
            chat_id,
            stored_head_message_id=provider_head_message_id,
            incremental_cursor=None,
            last_synced_at=utcnow(),
            last_error=None,
        )

    def advance_backfill(
        self,
        *,
        creator_id: str,
        chat_id: str,
        cursor: str | None,
    ) -> None:
        self._update(
            creator_id,
            chat_id,
            backfill_cursor=cursor,
            history_complete=cursor is None,
            last_synced_at=utcnow(),
            last_error=None,
        )

    def mark_error(
        self,
        *,
        creator_id: str,
        chat_id: str,
        error: Exception,
    ) -> None:
        self._update(
            creator_id,
            chat_id,
            last_error=type(error).__name__,
        )

    def _update(self, creator_id: str, chat_id: str, **values) -> None:
        values["updated_at"] = utcnow()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(CRM_CHAT_SYNC)
                .where(
                    and_(
                        CRM_CHAT_SYNC.c.creator_id == creator_id,
                        CRM_CHAT_SYNC.c.chat_id == chat_id,
                    )
                )
                .values(**values)
            )
        if result.rowcount != 1:
            raise RuntimeError(
                f"CRM sync state does not exist: {creator_id}/{chat_id}"
            )

    @staticmethod
    def _different(left, right):
        return or_(
            left != right,
            and_(left.is_(None), right.is_not(None)),
            and_(left.is_not(None), right.is_(None)),
        )

    @staticmethod
    def _state(row) -> CrmChatSyncState:
        return CrmChatSyncState(
            creator_id=row["creator_id"],
            chat_id=row["chat_id"],
            fan_id=row["fan_id"],
            provider_head_message_id=row["provider_head_message_id"],
            stored_head_message_id=row["stored_head_message_id"],
            incremental_cursor=row["incremental_cursor"],
            backfill_cursor=row["backfill_cursor"],
            history_complete=bool(row["history_complete"]),
            last_synced_at=row["last_synced_at"],
            last_error=row["last_error"],
        )

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
