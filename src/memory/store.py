"""MessageStore — SQLAlchemy-backed persistence of every fan conversation.

Every message (fan-sent and bot-sent) is stored so the bot remembers
everything across restarts. Used for:
- Injecting recent history into reply generation
- Dashboard conversation views
- Feeding the LLM fact extractor
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, desc
from src.persistence.database import create_database_engine
from src.persistence.schema import FAN_MESSAGES

logger = logging.getLogger(__name__)

MESSAGES_TABLE = FAN_MESSAGES


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
    ):
        """Persist a single message."""
        with self.engine.connect() as conn:
            conn.execute(
                MESSAGES_TABLE.insert().values(
                    fan_id=fan_id,
                    creator_id=creator_id,
                    sender=sender,
                    content=content,
                    message_id=message_id,
                    created_at=datetime.now(timezone.utc),
                )
            )
            conn.commit()

    def get_history(self, fan_id: str, creator_id: str, limit: int = 50) -> list[dict]:
        """Get recent messages for a fan, oldest first."""
        with self.engine.connect() as conn:
            stmt = (
                select(MESSAGES_TABLE)
                .where(
                    (MESSAGES_TABLE.c.fan_id == fan_id)
                    & (MESSAGES_TABLE.c.creator_id == creator_id)
                )
                .order_by(desc(MESSAGES_TABLE.c.id))
                .limit(limit)
            )
            rows = conn.execute(stmt).fetchall()
        return [
            {
                "sender": r.sender,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reversed(rows)
        ]

    def get_recent_context(self, fan_id: str, creator_id: str, limit: int = 10) -> str:
        """Format recent history as a chat transcript for LLM/script context."""
        msgs = self.get_history(fan_id, creator_id, limit=limit)
        lines = []
        for m in msgs:
            speaker = "Fan" if m["sender"] == "fan" else "Creator"
            lines.append(f"{speaker}: {m['content']}")
        return "\n".join(lines)

    def count_messages(self, fan_id: str, creator_id: str) -> int:
        with self.engine.connect() as conn:
            stmt = select(MESSAGES_TABLE.c.id).where(
                (MESSAGES_TABLE.c.fan_id == fan_id)
                & (MESSAGES_TABLE.c.creator_id == creator_id)
            )
            return len(conn.execute(stmt).fetchall())
