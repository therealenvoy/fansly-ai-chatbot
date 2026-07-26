"""Transactional inbox/outbox state for durable message processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .schema import (
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROCESSED_PLATFORM_MESSAGES,
    utcnow,
)


INBOUND_PENDING = "pending"
INBOUND_PROCESSING = "processing"
INBOUND_COMPLETED = "completed"
INBOUND_FAILED = "failed"

OUTBOX_PENDING = "pending"
OUTBOX_SENDING = "sending"
OUTBOX_SENT = "sent"
OUTBOX_DELIVERY_UNKNOWN = "delivery_unknown"


@dataclass(frozen=True)
class InboundMessageRecord:
    id: int
    creator_id: str
    platform_message_id: str
    fan_id: str
    chat_id: str
    content: str
    provider_created_at: datetime
    status: str
    attempt_count: int
    locked_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class OutboxMessageRecord:
    id: int
    inbound_message_id: int
    creator_id: str
    fan_id: str
    chat_id: str
    content: str
    status: str
    provider_message_id: str | None
    attempt_count: int
    created_at: datetime
    sent_at: datetime | None
    last_error: str | None


class MessageProcessingRepository:
    """Owns inbox/outbox transitions and their concurrency guarantees."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def insert_inbound(
        self,
        *,
        creator_id: str,
        platform_message_id: str,
        fan_id: str,
        chat_id: str,
        content: str,
        provider_created_at: datetime,
    ) -> tuple[InboundMessageRecord, bool]:
        """Insert once by provider message ID and return ``(row, created)``."""
        values = {
            "creator_id": creator_id,
            "platform_message_id": platform_message_id,
            "fan_id": fan_id,
            "chat_id": chat_id,
            "content": content,
            "provider_created_at": provider_created_at,
            "observed_at": utcnow(),
            "status": INBOUND_PENDING,
            "attempt_count": 0,
        }
        stmt = self._insert(INBOUND_MESSAGES).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["creator_id", "platform_message_id"]
        )
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
            created = result.rowcount == 1
            row = conn.execute(
                select(INBOUND_MESSAGES).where(
                    and_(
                        INBOUND_MESSAGES.c.creator_id == creator_id,
                        INBOUND_MESSAGES.c.platform_message_id
                        == platform_message_id,
                    )
                )
            ).mappings().one()
        return self._inbound(row), created

    def claim_next_inbound(
        self,
        creator_id: str,
    ) -> InboundMessageRecord | None:
        """Atomically claim the oldest pending inbound message.

        PostgreSQL workers skip rows locked by another worker. The status
        compare-and-set also protects SQLite test/dev mode.
        """
        with self.engine.begin() as conn:
            stmt = self.inbound_claim_statement(
                creator_id,
                skip_locked=self.engine.dialect.name == "postgresql",
            )
            row = conn.execute(stmt).mappings().first()
            if row is None:
                return None
            locked_at = utcnow()
            claimed = conn.execute(
                update(INBOUND_MESSAGES)
                .where(
                    and_(
                        INBOUND_MESSAGES.c.id == row["id"],
                        INBOUND_MESSAGES.c.status == INBOUND_PENDING,
                    )
                )
                .values(
                    status=INBOUND_PROCESSING,
                    locked_at=locked_at,
                    attempt_count=INBOUND_MESSAGES.c.attempt_count + 1,
                    last_error=None,
                )
            )
            if claimed.rowcount != 1:
                return None
            claimed_row = conn.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id == row["id"]
                )
            ).mappings().one()
        return self._inbound(claimed_row)

    def get_outbox_for_inbound(
        self,
        inbound_message_id: int,
    ) -> OutboxMessageRecord | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.inbound_message_id
                    == inbound_message_id
                )
            ).mappings().first()
        return self._outbox(row) if row else None

    def enqueue_outbox(
        self,
        *,
        inbound: InboundMessageRecord,
        content: str,
    ) -> tuple[OutboxMessageRecord, bool]:
        """Persist one approved response per inbound message."""
        values = {
            "inbound_message_id": inbound.id,
            "creator_id": inbound.creator_id,
            "fan_id": inbound.fan_id,
            "chat_id": inbound.chat_id,
            "content": content,
            "status": OUTBOX_PENDING,
            "attempt_count": 0,
            "created_at": utcnow(),
        }
        stmt = self._insert(OUTBOX_MESSAGES).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["inbound_message_id"]
        )
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
            created = result.rowcount == 1
            row = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.inbound_message_id == inbound.id
                )
            ).mappings().one()
        return self._outbox(row), created

    def claim_outbox(
        self,
        outbox_id: int,
    ) -> OutboxMessageRecord | None:
        """Commit ``sending`` before the external API call.

        A row that reached ``sending`` is never automatically sent again.
        This deliberately closes the duplicate-send crash window at the cost
        of requiring reconciliation if the process dies before recording the
        provider response.
        """
        with self.engine.begin() as conn:
            row = conn.execute(
                select(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .with_for_update()
            ).mappings().first()
            if row is None or row["status"] != OUTBOX_PENDING:
                return None
            result = conn.execute(
                update(OUTBOX_MESSAGES)
                .where(
                    and_(
                        OUTBOX_MESSAGES.c.id == outbox_id,
                        OUTBOX_MESSAGES.c.status == OUTBOX_PENDING,
                    )
                )
                .values(
                    status=OUTBOX_SENDING,
                    attempt_count=OUTBOX_MESSAGES.c.attempt_count + 1,
                    last_error=None,
                )
            )
            if result.rowcount != 1:
                return None
            claimed = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.id == outbox_id
                )
            ).mappings().one()
        return self._outbox(claimed)

    def complete_delivery(
        self,
        outbox_id: int,
        provider_message_id: str,
    ) -> tuple[OutboxMessageRecord, InboundMessageRecord]:
        """Record the provider ID and complete inbound atomically."""
        if not provider_message_id:
            raise ValueError("provider_message_id is required")
        now = utcnow()
        with self.engine.begin() as conn:
            outbox = conn.execute(
                select(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .with_for_update()
            ).mappings().one()
            if outbox["status"] != OUTBOX_SENDING:
                raise RuntimeError(
                    f"Outbox {outbox_id} is {outbox['status']}, not sending"
                )
            conn.execute(
                update(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .values(
                    status=OUTBOX_SENT,
                    provider_message_id=provider_message_id,
                    sent_at=now,
                    last_error=None,
                )
            )
            conn.execute(
                update(INBOUND_MESSAGES)
                .where(
                    INBOUND_MESSAGES.c.id == outbox["inbound_message_id"]
                )
                .values(
                    status=INBOUND_COMPLETED,
                    completed_at=now,
                    locked_at=None,
                    last_error=None,
                )
            )
            inbound = conn.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id
                    == outbox["inbound_message_id"]
                )
            ).mappings().one()
            processed = self._insert(PROCESSED_PLATFORM_MESSAGES).values(
                creator_id=inbound["creator_id"],
                platform_message_id=inbound["platform_message_id"],
                fan_id=inbound["fan_id"],
                chat_id=inbound["chat_id"],
                processed_at=now,
            )
            conn.execute(
                processed.on_conflict_do_nothing(
                    index_elements=[
                        "creator_id",
                        "platform_message_id",
                    ]
                )
            )
            sent = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.id == outbox_id
                )
            ).mappings().one()
        return self._outbox(sent), self._inbound(inbound)

    def complete_without_response(
        self,
        inbound_id: int,
    ) -> InboundMessageRecord:
        """Complete an inbound that policy intentionally produced no reply for."""
        now = utcnow()
        with self.engine.begin() as conn:
            inbound = conn.execute(
                select(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == inbound_id)
                .with_for_update()
            ).mappings().one()
            if inbound["status"] != INBOUND_PROCESSING:
                raise RuntimeError(
                    f"Inbound {inbound_id} is {inbound['status']}, not processing"
                )
            conn.execute(
                update(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == inbound_id)
                .values(
                    status=INBOUND_COMPLETED,
                    completed_at=now,
                    locked_at=None,
                    last_error=None,
                )
            )
            processed = self._insert(PROCESSED_PLATFORM_MESSAGES).values(
                creator_id=inbound["creator_id"],
                platform_message_id=inbound["platform_message_id"],
                fan_id=inbound["fan_id"],
                chat_id=inbound["chat_id"],
                processed_at=now,
            )
            conn.execute(
                processed.on_conflict_do_nothing(
                    index_elements=[
                        "creator_id",
                        "platform_message_id",
                    ]
                )
            )
            completed = conn.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id == inbound_id
                )
            ).mappings().one()
        return self._inbound(completed)

    def release_inbound(
        self,
        inbound_id: int,
        error: str,
        *,
        max_attempts: int = 3,
    ) -> InboundMessageRecord:
        """Retry a pre-send processing failure, then quarantine it."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == inbound_id)
                .with_for_update()
            ).mappings().one()
            next_status = (
                INBOUND_PENDING
                if row["attempt_count"] < max_attempts
                else INBOUND_FAILED
            )
            conn.execute(
                update(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == inbound_id)
                .values(
                    status=next_status,
                    locked_at=None,
                    last_error=self._error(error),
                )
            )
            released = conn.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id == inbound_id
                )
            ).mappings().one()
        return self._inbound(released)

    def mark_delivery_unknown(
        self,
        outbox_id: int,
        error: str,
    ) -> OutboxMessageRecord:
        """Quarantine an attempted send instead of risking a duplicate."""
        with self.engine.begin() as conn:
            outbox = conn.execute(
                select(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .with_for_update()
            ).mappings().one()
            if outbox["status"] != OUTBOX_SENDING:
                raise RuntimeError(
                    f"Outbox {outbox_id} is {outbox['status']}, not sending"
                )
            conn.execute(
                update(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .values(
                    status=OUTBOX_DELIVERY_UNKNOWN,
                    last_error=self._error(error),
                )
            )
            conn.execute(
                update(INBOUND_MESSAGES)
                .where(
                    INBOUND_MESSAGES.c.id
                    == outbox["inbound_message_id"]
                )
                .values(
                    status=INBOUND_FAILED,
                    locked_at=None,
                    last_error="outbox delivery outcome unknown",
                )
            )
            updated = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.id == outbox_id
                )
            ).mappings().one()
        return self._outbox(updated)

    def recover_interrupted(self, creator_id: str) -> dict[str, int]:
        """Recover only work that is provably safe after a restart.

        Pending outbox work is safe because no send attempt started. An outbox
        left in ``sending`` is quarantined because the provider may have
        accepted it before the process stopped.
        """
        counts = {"requeued": 0, "delivery_unknown": 0, "completed": 0}
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(INBOUND_MESSAGES).where(
                    and_(
                        INBOUND_MESSAGES.c.creator_id == creator_id,
                        INBOUND_MESSAGES.c.status == INBOUND_PROCESSING,
                    )
                )
            ).mappings().all()
            for inbound in rows:
                outbox = conn.execute(
                    select(OUTBOX_MESSAGES).where(
                        OUTBOX_MESSAGES.c.inbound_message_id == inbound["id"]
                    )
                ).mappings().first()
                if outbox is None or outbox["status"] == OUTBOX_PENDING:
                    conn.execute(
                        update(INBOUND_MESSAGES)
                        .where(INBOUND_MESSAGES.c.id == inbound["id"])
                        .values(
                            status=INBOUND_PENDING,
                            locked_at=None,
                            last_error="recovered interrupted processing",
                        )
                    )
                    counts["requeued"] += 1
                elif outbox["status"] == OUTBOX_SENT:
                    conn.execute(
                        update(INBOUND_MESSAGES)
                        .where(INBOUND_MESSAGES.c.id == inbound["id"])
                        .values(
                            status=INBOUND_COMPLETED,
                            completed_at=outbox["sent_at"] or utcnow(),
                            locked_at=None,
                            last_error=None,
                        )
                    )
                    processed = self._insert(
                        PROCESSED_PLATFORM_MESSAGES
                    ).values(
                        creator_id=inbound["creator_id"],
                        platform_message_id=inbound[
                            "platform_message_id"
                        ],
                        fan_id=inbound["fan_id"],
                        chat_id=inbound["chat_id"],
                        processed_at=outbox["sent_at"] or utcnow(),
                    )
                    conn.execute(
                        processed.on_conflict_do_nothing(
                            index_elements=[
                                "creator_id",
                                "platform_message_id",
                            ]
                        )
                    )
                    counts["completed"] += 1
                elif outbox["status"] == OUTBOX_SENDING:
                    conn.execute(
                        update(OUTBOX_MESSAGES)
                        .where(OUTBOX_MESSAGES.c.id == outbox["id"])
                        .values(
                            status=OUTBOX_DELIVERY_UNKNOWN,
                            last_error="process stopped during provider send",
                        )
                    )
                    conn.execute(
                        update(INBOUND_MESSAGES)
                        .where(INBOUND_MESSAGES.c.id == inbound["id"])
                        .values(
                            status=INBOUND_FAILED,
                            locked_at=None,
                            last_error="outbox delivery outcome unknown",
                        )
                    )
                    counts["delivery_unknown"] += 1
        return counts

    def counts(self, creator_id: str) -> dict[str, int]:
        """Return status counts for tests and operational diagnostics."""
        result: dict[str, int] = {}
        with self.engine.connect() as conn:
            for status, count in conn.execute(
                select(
                    INBOUND_MESSAGES.c.status,
                    func.count(INBOUND_MESSAGES.c.id),
                )
                .where(INBOUND_MESSAGES.c.creator_id == creator_id)
                .group_by(INBOUND_MESSAGES.c.status)
            ):
                result[f"inbound_{status}"] = int(count)
            for status, count in conn.execute(
                select(
                    OUTBOX_MESSAGES.c.status,
                    func.count(OUTBOX_MESSAGES.c.id),
                )
                .where(OUTBOX_MESSAGES.c.creator_id == creator_id)
                .group_by(OUTBOX_MESSAGES.c.status)
            ):
                result[f"outbox_{status}"] = int(count)
        return result

    @staticmethod
    def inbound_claim_statement(
        creator_id: str,
        *,
        skip_locked: bool,
    ):
        earlier = INBOUND_MESSAGES.alias("earlier_inbound")
        earlier_nonterminal = exists(
            select(1).where(
                and_(
                    earlier.c.creator_id
                    == INBOUND_MESSAGES.c.creator_id,
                    earlier.c.status.in_(
                        [INBOUND_PENDING, INBOUND_PROCESSING]
                    ),
                    or_(
                        earlier.c.provider_created_at
                        < INBOUND_MESSAGES.c.provider_created_at,
                        and_(
                            earlier.c.provider_created_at
                            == INBOUND_MESSAGES.c.provider_created_at,
                            earlier.c.id < INBOUND_MESSAGES.c.id,
                        ),
                    ),
                )
            )
        )
        stmt = (
            select(INBOUND_MESSAGES)
            .where(
                and_(
                    INBOUND_MESSAGES.c.creator_id == creator_id,
                    INBOUND_MESSAGES.c.status == INBOUND_PENDING,
                    ~earlier_nonterminal,
                )
            )
            .order_by(
                INBOUND_MESSAGES.c.provider_created_at.asc(),
                INBOUND_MESSAGES.c.id.asc(),
            )
            .limit(1)
        )
        return (
            stmt.with_for_update(skip_locked=True)
            if skip_locked
            else stmt
        )

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )

    @staticmethod
    def _error(error: str) -> str:
        return str(error).strip()[:2000] or "unknown error"

    @staticmethod
    def _inbound(row) -> InboundMessageRecord:
        return InboundMessageRecord(
            id=row["id"],
            creator_id=row["creator_id"],
            platform_message_id=row["platform_message_id"],
            fan_id=row["fan_id"],
            chat_id=row["chat_id"],
            content=row["content"],
            provider_created_at=row["provider_created_at"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            locked_at=row["locked_at"],
            completed_at=row["completed_at"],
            last_error=row["last_error"],
        )

    @staticmethod
    def _outbox(row) -> OutboxMessageRecord:
        return OutboxMessageRecord(
            id=row["id"],
            inbound_message_id=row["inbound_message_id"],
            creator_id=row["creator_id"],
            fan_id=row["fan_id"],
            chat_id=row["chat_id"],
            content=row["content"],
            status=row["status"],
            provider_message_id=row["provider_message_id"],
            attempt_count=row["attempt_count"],
            created_at=row["created_at"],
            sent_at=row["sent_at"],
            last_error=row["last_error"],
        )
