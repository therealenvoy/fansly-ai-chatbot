"""Transactional inbox/outbox state for durable message processing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, and_, case, exists, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.messaging.models import OutboundMessage
from src.sequences.models import StepStatus
from src.sequences.repository import PROGRESS_TABLE, STEPS_TABLE

from .schema import (
    FAN_MESSAGES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROCESSED_PLATFORM_MESSAGES,
    CONTACT_CLAIMS,
    TRIGGER_OWNERSHIP,
    TRIGGER_OWNERSHIP_EVENTS,
    FAN_CONTACT_POLICIES,
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
OUTBOX_BLOCKED_UNSUPPORTED = "blocked_unsupported"
OUTBOX_BLOCKED_POLICY = "blocked_policy"
OUTBOX_BLOCKED_PROVIDER = "blocked_provider"


class InboundSupersededError(RuntimeError):
    """Conversation work became terminal before an outbox could be created."""


@dataclass(frozen=True)
class InboundMessageRecord:
    id: int
    creator_id: str
    platform_message_id: str
    fan_id: str
    chat_id: str
    content: str
    trigger_kind: str
    provider_created_at: datetime
    available_at: datetime
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
    message_kind: str
    media_ids: tuple[str, ...]
    price_millis: int | None
    sequence_id: int | None
    sequence_step_id: int | None
    status: str
    provider_message_id: str | None
    provider_purchase_ref: str | None
    attempt_count: int
    created_at: datetime
    sent_at: datetime | None
    last_error: str | None
    trigger_source: str
    service_role: str
    permit_status: str
    permit_expires_at: datetime | None
    contact_policy_version: int


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
        trigger_kind: str = "unread",
        available_at: datetime | None = None,
    ) -> tuple[InboundMessageRecord, bool]:
        """Insert once by provider message ID and return ``(row, created)``."""
        observed_at = utcnow()
        values = {
            "creator_id": creator_id,
            "platform_message_id": platform_message_id,
            "fan_id": fan_id,
            "chat_id": chat_id,
            "content": content,
            "trigger_kind": trigger_kind,
            "provider_created_at": provider_created_at,
            "observed_at": observed_at,
            "available_at": available_at or observed_at,
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

    def insert_inbound_many(self, messages: list[dict]) -> int:
        """Bulk-insert durable inbound work and return the created row count."""
        if not messages:
            return 0
        observed_at = utcnow()
        values = [
            {
                "creator_id": str(message["creator_id"]),
                "platform_message_id": str(
                    message["platform_message_id"]
                ),
                "fan_id": str(message["fan_id"]),
                "chat_id": str(message["chat_id"]),
                "content": str(message.get("content") or ""),
                "trigger_kind": str(
                    message.get("trigger_kind") or "unread"
                ),
                "provider_created_at": message["provider_created_at"],
                "observed_at": observed_at,
                "available_at": (
                    message.get("available_at") or observed_at
                ),
                "status": INBOUND_PENDING,
                "attempt_count": 0,
            }
            for message in messages
        ]
        created = 0
        with self.engine.begin() as conn:
            for offset in range(0, len(values), 500):
                statement = self._insert(INBOUND_MESSAGES).values(
                    values[offset : offset + 500]
                )
                statement = statement.on_conflict_do_nothing(
                    index_elements=[
                        "creator_id",
                        "platform_message_id",
                    ]
                )
                result = conn.execute(statement)
                created += max(int(result.rowcount or 0), 0)
        return created

    def claim_next_inbound(
        self,
        creator_id: str,
        *,
        allowed_fan_ids: set[str] | None = None,
        now: datetime | None = None,
    ) -> InboundMessageRecord | None:
        """Atomically claim the oldest pending inbound message.

        PostgreSQL workers skip rows locked by another worker. The status
        compare-and-set also protects SQLite test/dev mode.
        """
        with self.engine.begin() as conn:
            stmt = self.inbound_claim_statement(
                creator_id,
                skip_locked=self.engine.dialect.name == "postgresql",
                allowed_fan_ids=allowed_fan_ids,
                now=now,
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

    def get_inbound(self, inbound_message_id: int) -> InboundMessageRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id == inbound_message_id
                )
            ).mappings().first()
        return self._inbound(row) if row else None

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
        message: OutboundMessage | None = None,
        content: str | None = None,
        service_role: str = "current_brain",
    ) -> tuple[OutboxMessageRecord, bool]:
        """Persist one approved response per inbound message."""
        if message is None:
            if content is None:
                raise ValueError("message is required")
            message = OutboundMessage.text(content)
        values = {
            "inbound_message_id": inbound.id,
            "creator_id": inbound.creator_id,
            "fan_id": inbound.fan_id,
            "chat_id": inbound.chat_id,
            "content": message.content,
            "message_kind": message.kind.value,
            "media_ids": list(message.media_ids),
            "price_millis": message.price_millis,
            "sequence_id": message.sequence_id,
            "sequence_step_id": message.sequence_step_id,
            "status": OUTBOX_PENDING,
            "attempt_count": 0,
            "created_at": utcnow(),
        }
        policy_version = 0
        with self.engine.connect() as connection:
            policy_version = int(
                connection.execute(
                    select(FAN_CONTACT_POLICIES.c.version).where(
                        and_(
                            FAN_CONTACT_POLICIES.c.creator_id == inbound.creator_id,
                            FAN_CONTACT_POLICIES.c.fan_id == inbound.fan_id,
                        )
                    )
                ).scalar_one_or_none() or 0
            )
        values.update(trigger_source=inbound.trigger_kind, service_role=service_role, permit_status="approved", permit_expires_at=utcnow() + timedelta(minutes=15), contact_policy_version=policy_version)
        stmt = self._insert(OUTBOX_MESSAGES).values(**values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["inbound_message_id"]
        )
        with self.engine.begin() as conn:
            current_status = conn.execute(
                select(INBOUND_MESSAGES.c.status)
                .where(INBOUND_MESSAGES.c.id == inbound.id)
                .with_for_update()
            ).scalar_one()
            allowed_statuses = {INBOUND_PROCESSING}
            if inbound.status == INBOUND_PENDING:
                allowed_statuses.add(INBOUND_PENDING)
            if current_status not in allowed_statuses:
                raise InboundSupersededError(
                    "inbound work was superseded before outbox creation"
                )
            self._ensure_trigger_ownership_defaults(conn, inbound.creator_id)
            result = conn.execute(stmt)
            created = result.rowcount == 1
            row = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.inbound_message_id == inbound.id
                )
            ).mappings().one()
        return self._outbox(row), created

    def complete_unsupported(
        self,
        outbox_id: int,
        reason: str,
    ) -> tuple[OutboxMessageRecord, InboundMessageRecord]:
        """Complete an inbound while preserving a blocked delivery intent."""
        now = utcnow()
        with self.engine.begin() as conn:
            outbox = conn.execute(
                select(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .with_for_update()
            ).mappings().one()
            if outbox["status"] != OUTBOX_PENDING:
                raise RuntimeError(
                    f"Outbox {outbox_id} is {outbox['status']}, not pending"
                )
            conn.execute(
                update(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .values(
                    status=OUTBOX_BLOCKED_UNSUPPORTED,
                    last_error=self._error(reason),
                )
            )
            inbound_id = outbox["inbound_message_id"]
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
            inbound = conn.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id == inbound_id
                )
            ).mappings().one()
            self._insert_processed(conn, inbound, now)
            blocked = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    OUTBOX_MESSAGES.c.id == outbox_id
                )
            ).mappings().one()
        return self._outbox(blocked), self._inbound(inbound)

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
            now = utcnow()
            row = conn.execute(
                select(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .with_for_update()
            ).mappings().first()
            if row is None or row["status"] != OUTBOX_PENDING:
                return None
            policy = conn.execute(
                select(FAN_CONTACT_POLICIES).where(
                    and_(
                        FAN_CONTACT_POLICIES.c.creator_id == row["creator_id"],
                        FAN_CONTACT_POLICIES.c.fan_id == row["fan_id"],
                    )
                )
            ).mappings().first()
            permit_expires_at = row["permit_expires_at"]
            paused_until = policy["paused_until"] if policy else None
            compare_now = now
            if permit_expires_at is not None and permit_expires_at.tzinfo is None:
                compare_now = now.replace(tzinfo=None)
            inbound = conn.execute(
                select(INBOUND_MESSAGES).where(
                    INBOUND_MESSAGES.c.id == row["inbound_message_id"]
                )
            ).mappings().one()
            trigger_type = {
                "unread": "inbound_reply",
                "online": "online",
                "stalled": "stalled",
            }.get(str(row["trigger_source"]), str(row["trigger_source"]))
            owner = conn.execute(
                select(TRIGGER_OWNERSHIP.c.owner).where(
                    and_(
                        TRIGGER_OWNERSHIP.c.creator_id == row["creator_id"],
                        TRIGGER_OWNERSHIP.c.trigger_type == trigger_type,
                    )
                )
            ).scalar_one_or_none()
            claim_key = hashlib.sha256(
                "\0".join(
                    (
                        str(row["creator_id"]),
                        str(row["fan_id"]),
                        trigger_type,
                        str(inbound["platform_message_id"]),
                    )
                ).encode("utf-8")
            ).hexdigest()
            existing_claim = conn.execute(
                select(CONTACT_CLAIMS).where(
                    and_(
                        CONTACT_CLAIMS.c.creator_id == row["creator_id"],
                        CONTACT_CLAIMS.c.idempotency_key == claim_key,
                    )
                )
            ).mappings().first()
            policy_block = (
                row["permit_status"] != "approved"
                or permit_expires_at is None
                or permit_expires_at <= compare_now
                or (policy is not None and bool(policy["do_not_contact"]))
                or (paused_until is not None and paused_until > compare_now)
                or int(row["contact_policy_version"] or 0) != int(policy["version"] if policy else 0)
                or owner != row["service_role"]
                or (existing_claim is not None and existing_claim["source_system"] != row["service_role"])
            )
            if policy_block:
                conn.execute(update(OUTBOX_MESSAGES).where(OUTBOX_MESSAGES.c.id == outbox_id).values(status=OUTBOX_BLOCKED_POLICY, permit_status="revoked", last_error="send permit rejected by current contact policy"))
                conn.execute(update(INBOUND_MESSAGES).where(INBOUND_MESSAGES.c.id == row["inbound_message_id"]).values(status=INBOUND_COMPLETED, completed_at=now, locked_at=None, last_error=None))
                inbound = conn.execute(select(INBOUND_MESSAGES).where(INBOUND_MESSAGES.c.id == row["inbound_message_id"])).mappings().one()
                self._insert_processed(conn, inbound, now)
                return None
            if existing_claim is None:
                claim_stmt = self._insert(CONTACT_CLAIMS).values(
                    creator_id=row["creator_id"],
                    fan_id=row["fan_id"],
                    trigger_type=trigger_type,
                    trigger_event_id=inbound["platform_message_id"],
                    source_system=row["service_role"],
                    campaign_or_automation_id=None,
                    idempotency_key=claim_key,
                    claimed_at=now,
                    cooldown_until=None,
                    outbox_id=row["id"],
                    native_message_hash=None,
                    status="claimed",
                    denial_reason=None,
                )
                claim_stmt = claim_stmt.on_conflict_do_nothing(
                    index_elements=["creator_id", "idempotency_key"]
                )
                if conn.execute(claim_stmt).rowcount != 1:
                    conn.execute(
                        update(OUTBOX_MESSAGES)
                        .where(OUTBOX_MESSAGES.c.id == outbox_id)
                        .values(status=OUTBOX_BLOCKED_POLICY, permit_status="revoked", last_error="contact episode was claimed concurrently")
                    )
                    conn.execute(
                        update(INBOUND_MESSAGES)
                        .where(INBOUND_MESSAGES.c.id == row["inbound_message_id"])
                        .values(
                            status=INBOUND_COMPLETED,
                            completed_at=now,
                            locked_at=None,
                            last_error=None,
                        )
                    )
                    self._insert_processed(conn, inbound, now)
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
        provider_purchase_ref: str | None = None,
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
            ppv_step = self._ppv_step(conn, outbox)
            conn.execute(
                update(OUTBOX_MESSAGES)
                .where(OUTBOX_MESSAGES.c.id == outbox_id)
                .values(
                    status=OUTBOX_SENT,
                    provider_message_id=provider_message_id,
                    provider_purchase_ref=provider_purchase_ref,
                    sent_at=now,
                    last_error=None,
                )
            )
            conn.execute(
                update(FAN_MESSAGES)
                .where(
                    and_(
                        FAN_MESSAGES.c.creator_id
                        == outbox["creator_id"],
                        FAN_MESSAGES.c.message_id
                        == provider_message_id,
                    )
                )
                .values(source_class="ai")
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
            self._insert_processed(conn, inbound, now)
            if ppv_step is not None:
                self._mark_ppv_sent(
                    conn,
                    outbox=outbox,
                    step=ppv_step,
                    sent_at=now,
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
            self._insert_processed(conn, inbound, now)
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
        retry_base_seconds: int = 0,
        retry_max_seconds: int = 0,
        now: datetime | None = None,
    ) -> InboundMessageRecord:
        """Retry a pre-send processing failure, then quarantine it."""
        current_time = now or utcnow()
        with self.engine.begin() as conn:
            row = conn.execute(
                select(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == inbound_id)
                .with_for_update()
            ).mappings().one()
            if row["status"] != INBOUND_PROCESSING:
                return self._inbound(row)
            next_status = (
                INBOUND_PENDING
                if row["attempt_count"] < max_attempts
                else INBOUND_FAILED
            )
            retry_delay = 0
            if next_status == INBOUND_PENDING and retry_base_seconds > 0:
                retry_delay = retry_base_seconds * (
                    2 ** max(int(row["attempt_count"]) - 1, 0)
                )
                if retry_max_seconds > 0:
                    retry_delay = min(retry_delay, retry_max_seconds)
            conn.execute(
                update(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == inbound_id)
                .values(
                    status=next_status,
                    available_at=(
                        current_time + timedelta(seconds=retry_delay)
                    ),
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

    def mark_provider_blocked(
        self,
        outbox_id: int,
        error: str,
    ) -> OutboxMessageRecord:
        """Record a confirmed non-send without creating a duplicate-send risk."""
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
                    status=OUTBOX_BLOCKED_PROVIDER,
                    permit_status="revoked",
                    last_error=self._error(error),
                )
            )
            conn.execute(
                update(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == outbox["inbound_message_id"])
                .values(
                    status=INBOUND_FAILED,
                    locked_at=None,
                    last_error="provider confirmed message was not sent",
                )
            )
            updated = conn.execute(
                select(OUTBOX_MESSAGES).where(OUTBOX_MESSAGES.c.id == outbox_id)
            ).mappings().one()
        return self._outbox(updated)

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

    def block_pending_non_text(
        self,
        creator_id: str,
        reason: str,
    ) -> int:
        """Quarantine stale media/PPV work before conversation-mode launch."""
        now = utcnow()
        blocked = 0
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(OUTBOX_MESSAGES).where(
                    and_(
                        OUTBOX_MESSAGES.c.creator_id == creator_id,
                        OUTBOX_MESSAGES.c.status == OUTBOX_PENDING,
                        OUTBOX_MESSAGES.c.message_kind != "text",
                    )
                )
            ).mappings().all()
            for outbox in rows:
                conn.execute(
                    update(OUTBOX_MESSAGES)
                    .where(OUTBOX_MESSAGES.c.id == outbox["id"])
                    .values(
                        status=OUTBOX_BLOCKED_UNSUPPORTED,
                        last_error=self._error(reason),
                    )
                )
                inbound = conn.execute(
                    select(INBOUND_MESSAGES).where(
                        INBOUND_MESSAGES.c.id
                        == outbox["inbound_message_id"]
                    )
                ).mappings().one()
                conn.execute(
                    update(INBOUND_MESSAGES)
                    .where(INBOUND_MESSAGES.c.id == inbound["id"])
                    .values(
                        status=INBOUND_COMPLETED,
                        completed_at=now,
                        locked_at=None,
                        last_error=None,
                    )
                )
                self._insert_processed(conn, inbound, now)
                blocked += 1
        return blocked

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
        allowed_fan_ids: set[str] | None = None,
        now: datetime | None = None,
    ):
        allowed = (
            tuple(sorted(str(fan_id) for fan_id in allowed_fan_ids))
            if allowed_fan_ids is not None
            else None
        )
        earlier = INBOUND_MESSAGES.alias("earlier_inbound")
        candidate_priority = case(
            (INBOUND_MESSAGES.c.trigger_kind == "unread", 0),
            (INBOUND_MESSAGES.c.trigger_kind == "online", 1),
            (INBOUND_MESSAGES.c.trigger_kind == "stalled", 2),
            else_=3,
        )
        earlier_priority = case(
            (earlier.c.trigger_kind == "unread", 0),
            (earlier.c.trigger_kind == "online", 1),
            (earlier.c.trigger_kind == "stalled", 2),
            else_=3,
        )
        claim_time = now or utcnow()
        earlier_filters = [
            earlier.c.creator_id == INBOUND_MESSAGES.c.creator_id,
            earlier.c.fan_id == INBOUND_MESSAGES.c.fan_id,
            earlier.c.status.in_(
                [INBOUND_PENDING, INBOUND_PROCESSING]
            ),
        ]
        candidate_filters = [
            INBOUND_MESSAGES.c.creator_id == creator_id,
            INBOUND_MESSAGES.c.status == INBOUND_PENDING,
            INBOUND_MESSAGES.c.available_at <= claim_time,
        ]
        if allowed is not None:
            earlier_filters.append(earlier.c.fan_id.in_(allowed))
            candidate_filters.append(
                INBOUND_MESSAGES.c.fan_id.in_(allowed)
            )
        earlier_nonterminal = exists(
            select(1).where(
                and_(
                    *earlier_filters,
                    or_(
                        earlier_priority < candidate_priority,
                        and_(
                            earlier_priority == candidate_priority,
                            or_(
                                earlier.c.provider_created_at
                                < INBOUND_MESSAGES.c.provider_created_at,
                                and_(
                                    earlier.c.provider_created_at
                                    == INBOUND_MESSAGES.c.provider_created_at,
                                    earlier.c.id < INBOUND_MESSAGES.c.id,
                                ),
                            ),
                        ),
                        earlier.c.status == INBOUND_PROCESSING,
                    ),
                )
            )
        )
        stmt = (
            select(INBOUND_MESSAGES)
            .where(
                and_(
                    *candidate_filters,
                    ~earlier_nonterminal,
                )
            )
            .order_by(
                candidate_priority.asc(),
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

    def _insert_processed(self, conn, inbound, processed_at: datetime) -> None:
        processed = self._insert(PROCESSED_PLATFORM_MESSAGES).values(
            creator_id=inbound["creator_id"],
            platform_message_id=inbound["platform_message_id"],
            fan_id=inbound["fan_id"],
            chat_id=inbound["chat_id"],
            processed_at=processed_at,
        )
        conn.execute(
            processed.on_conflict_do_nothing(
                index_elements=[
                    "creator_id",
                    "platform_message_id",
                ]
            )
        )

    @staticmethod
    def _ppv_step(conn, outbox):
        if outbox["message_kind"] != "ppv":
            return None
        if (
            outbox["sequence_id"] is None
            or outbox["sequence_step_id"] is None
        ):
            raise RuntimeError("PPV outbox lacks sequence provenance")
        step = conn.execute(
            select(STEPS_TABLE).where(
                and_(
                    STEPS_TABLE.c.id == outbox["sequence_step_id"],
                    STEPS_TABLE.c.sequence_id == outbox["sequence_id"],
                )
            )
        ).mappings().first()
        if step is None:
            raise RuntimeError("PPV sequence step does not exist")
        return step

    def _mark_ppv_sent(
        self,
        conn,
        *,
        outbox,
        step,
        sent_at: datetime,
    ) -> None:
        values = {
            "fan_id": outbox["fan_id"],
            "sequence_id": outbox["sequence_id"],
            "creator_id": outbox["creator_id"],
            "current_step": step["position"] + 1,
            "status": StepStatus.SENT.value,
            "last_sent_at": sent_at,
            "bought_at": None,
            "started_at": sent_at,
        }
        statement = self._insert(PROGRESS_TABLE).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                "fan_id",
                "sequence_id",
                "creator_id",
            ],
            set_={
                "current_step": step["position"] + 1,
                "status": StepStatus.SENT.value,
                "last_sent_at": sent_at,
                "bought_at": None,
            },
        )
        conn.execute(statement)

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
            trigger_kind=row["trigger_kind"],
            provider_created_at=row["provider_created_at"],
            available_at=row["available_at"],
            status=row["status"],
            attempt_count=row["attempt_count"],
            locked_at=row["locked_at"],
            completed_at=row["completed_at"],
            last_error=row["last_error"],
        )

    @staticmethod
    def _ensure_trigger_ownership_defaults(conn, creator_id: str) -> None:
        now = utcnow()
        defaults = {
            "new_follower": "disabled",
            "new_subscriber": "disabled",
            "gift_subscriber": "disabled",
            "renewal": "disabled",
            "qualifying_tip": "disabled",
            "online": "disabled",
            "stalled": "disabled",
            "inbound_reply": "current_brain",
        }
        for trigger_type, owner in defaults.items():
            statement = MessageProcessingRepository._dialect_insert(
                conn.dialect.name,
                TRIGGER_OWNERSHIP,
            ).values(
                creator_id=creator_id,
                trigger_type=trigger_type,
                owner=owner,
                version=1,
                updated_by="system_default",
                updated_at=now,
            )
            statement = statement.on_conflict_do_nothing(
                index_elements=["creator_id", "trigger_type"]
            )
            if conn.execute(statement).rowcount == 1:
                conn.execute(
                    insert(TRIGGER_OWNERSHIP_EVENTS).values(
                        creator_id=creator_id,
                        trigger_type=trigger_type,
                        previous_owner=None,
                        new_owner=owner,
                        actor="system_default",
                        reason="safe_initial_ownership",
                        created_at=now,
                    )
                )

    @staticmethod
    def _dialect_insert(dialect_name: str, table):
        return pg_insert(table) if dialect_name == "postgresql" else sqlite_insert(table)

    @staticmethod
    def _outbox(row) -> OutboxMessageRecord:
        return OutboxMessageRecord(
            id=row["id"],
            inbound_message_id=row["inbound_message_id"],
            creator_id=row["creator_id"],
            fan_id=row["fan_id"],
            chat_id=row["chat_id"],
            content=row["content"],
            message_kind=row["message_kind"],
            media_ids=tuple(row["media_ids"] or []),
            price_millis=row["price_millis"],
            sequence_id=row["sequence_id"],
            sequence_step_id=row["sequence_step_id"],
            status=row["status"],
            provider_message_id=row["provider_message_id"],
            provider_purchase_ref=row["provider_purchase_ref"],
            attempt_count=row["attempt_count"],
            created_at=row["created_at"],
            sent_at=row["sent_at"],
            last_error=row["last_error"],
            trigger_source=row["trigger_source"],
            service_role=row["service_role"],
            permit_status=row["permit_status"],
            permit_expires_at=row["permit_expires_at"],
            contact_policy_version=int(row["contact_policy_version"] or 0),
        )
