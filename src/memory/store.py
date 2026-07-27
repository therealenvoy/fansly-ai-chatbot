"""MessageStore — SQLAlchemy-backed persistence of every fan conversation.

Every message (fan-sent and bot-sent) is stored so the bot remembers
everything across restarts. Used for:
- Injecting recent history into reply generation
- Dashboard conversation views
- Feeding the LLM fact extractor
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, desc, func, select
from src.persistence.database import create_database_engine
from src.persistence.schema import FAN_MESSAGES

logger = logging.getLogger(__name__)

MESSAGES_TABLE = FAN_MESSAGES


@dataclass(frozen=True)
class MessageHistoryPage:
    messages: list[dict]
    total: int
    offset: int
    limit: int
    has_more: bool


class MessageStore:
    """SQLAlchemy-backed store for all fan conversation messages."""

    def __init__(self, db_url: str | None = None, *, engine=None):
        if engine is None and db_url is None:
            raise ValueError("db_url or engine is required")
        self.engine = engine or create_database_engine(db_url)

    def create_table(self):
        """Create the table for isolated tests; production uses Alembic."""
        MESSAGES_TABLE.create(self.engine, checkfirst=True)

    def save_message(
        self,
        fan_id: str,
        creator_id: str,
        sender: str,
        content: str,
        message_id: Optional[str] = None,
        *,
        chat_id: str | None = None,
        attachments: list[dict] | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        """Persist a message once, preserving provider time and media metadata."""
        return bool(
            self.save_messages(
                [
                    {
                        "fan_id": fan_id,
                        "creator_id": creator_id,
                        "sender": sender,
                        "content": content,
                        "message_id": message_id,
                        "chat_id": chat_id,
                        "attachments": attachments,
                        "created_at": created_at,
                    }
                ]
            )
        )

    def save_messages(self, messages: list[dict]) -> int:
        """Persist a provider page with one dedupe read and one bulk insert."""
        if not messages:
            return 0
        now = datetime.now(timezone.utc)
        grouped_ids: dict[str, set[str]] = {}
        for message in messages:
            message_id = message.get("message_id")
            if message_id:
                grouped_ids.setdefault(
                    str(message["creator_id"]),
                    set(),
                ).add(str(message_id))

        with self.engine.begin() as conn:
            existing_ids: set[tuple[str, str]] = set()
            for creator_id, message_ids in grouped_ids.items():
                existing_ids.update(
                    (
                        str(row.creator_id),
                        str(row.message_id),
                    )
                    for row in conn.execute(
                        select(
                            MESSAGES_TABLE.c.creator_id,
                            MESSAGES_TABLE.c.message_id,
                        ).where(
                            and_(
                                MESSAGES_TABLE.c.creator_id == creator_id,
                                MESSAGES_TABLE.c.message_id.in_(message_ids),
                            )
                        )
                    )
                )

            insert_rows: list[dict] = []
            seen_ids = set(existing_ids)
            for message in messages:
                creator_id = str(message["creator_id"])
                message_id = message.get("message_id")
                dedupe_key = (
                    (creator_id, str(message_id))
                    if message_id
                    else None
                )
                if dedupe_key is not None and dedupe_key in seen_ids:
                    continue
                if dedupe_key is not None:
                    seen_ids.add(dedupe_key)
                insert_rows.append(
                    {
                        "fan_id": str(message["fan_id"]),
                        "creator_id": creator_id,
                        "chat_id": message.get("chat_id"),
                        "sender": str(message["sender"]),
                        "content": message.get("content") or "",
                        "message_id": message_id,
                        "attachments": list(
                            message.get("attachments") or []
                        ),
                        "created_at": message.get("created_at") or now,
                    }
                )
            if insert_rows:
                conn.execute(MESSAGES_TABLE.insert(), insert_rows)
        return len(insert_rows)

    def get_history(self, fan_id: str, creator_id: str, limit: int = 50) -> list[dict]:
        """Get recent messages for a fan, oldest first."""
        return self.get_history_page(
            fan_id,
            creator_id,
            limit=limit,
        ).messages

    def get_history_page(
        self,
        fan_id: str,
        creator_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> MessageHistoryPage:
        """Return one newest-first window rendered in chronological order."""
        limit = min(max(int(limit), 1), 250)
        offset = max(int(offset), 0)
        predicate = and_(
            MESSAGES_TABLE.c.fan_id == fan_id,
            MESSAGES_TABLE.c.creator_id == creator_id,
        )
        with self.engine.connect() as conn:
            total = int(
                conn.execute(
                    select(func.count())
                    .select_from(MESSAGES_TABLE)
                    .where(predicate)
                ).scalar_one()
                or 0
            )
            stmt = (
                select(MESSAGES_TABLE)
                .where(predicate)
                .order_by(
                    desc(MESSAGES_TABLE.c.created_at),
                    desc(MESSAGES_TABLE.c.id),
                )
                .limit(limit)
                .offset(offset)
            )
            rows = conn.execute(stmt).fetchall()
        messages = [self._serialize(row) for row in reversed(rows)]
        return MessageHistoryPage(
            messages=messages,
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(rows) < total,
        )

    def get_recent_context(self, fan_id: str, creator_id: str, limit: int = 10) -> str:
        """Format recent history as a chat transcript for LLM/script context."""
        msgs = self.get_history(fan_id, creator_id, limit=limit)
        lines = []
        for m in msgs:
            speaker = "Fan" if m["sender"] == "fan" else "Creator"
            lines.append(f"{speaker}: {m['content']}")
        return "\n".join(lines)

    def get_latest_message(
        self,
        fan_id: str,
        creator_id: str,
        *,
        sender: str | None = None,
    ) -> dict | None:
        """Return the newest durable message, optionally for one sender."""
        filters = [
            MESSAGES_TABLE.c.fan_id == fan_id,
            MESSAGES_TABLE.c.creator_id == creator_id,
        ]
        if sender is not None:
            filters.append(MESSAGES_TABLE.c.sender == sender)
        statement = (
            select(MESSAGES_TABLE)
            .where(and_(*filters))
            .order_by(
                desc(MESSAGES_TABLE.c.created_at),
                desc(MESSAGES_TABLE.c.id),
            )
            .limit(1)
        )
        with self.engine.connect() as conn:
            row = conn.execute(statement).first()
        return self._serialize(row) if row is not None else None

    def count_messages(self, fan_id: str, creator_id: str) -> int:
        with self.engine.connect() as conn:
            stmt = select(func.count()).select_from(MESSAGES_TABLE).where(
                (MESSAGES_TABLE.c.fan_id == fan_id)
                & (MESSAGES_TABLE.c.creator_id == creator_id)
            )
            return int(conn.execute(stmt).scalar_one() or 0)

    @staticmethod
    def _serialize(row) -> dict:
        return {
            "id": int(row.id),
            "sender": row.sender,
            "content": row.content or "",
            "message_id": row.message_id,
            "chat_id": row.chat_id,
            "attachments": list(row.attachments or []),
            "created_at": (
                row.created_at.isoformat()
                if row.created_at
                else None
            ),
        }
