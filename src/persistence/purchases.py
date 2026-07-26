"""Truthful provider-ledger ingestion and attributed purchase application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.fansly_client import WalletTransaction
from src.notes.repository import FAN_NOTES_TABLE
from src.sequences.models import StepStatus
from src.sequences.repository import (
    PROGRESS_TABLE,
    STEPS_TABLE,
)

from .pipeline import OUTBOX_SENT
from .schema import (
    CREATORS,
    FAN_RUNTIME_STATES,
    OUTBOX_MESSAGES,
    PROVIDER_WALLET_TRANSACTIONS,
    PURCHASE_EVENTS,
    utcnow,
)


@dataclass(frozen=True)
class PurchaseEventRecord:
    id: int
    creator_id: str
    provider_purchase_id: str
    fan_id: str
    outbox_message_id: int
    provider_message_id: str
    amount_millis: int
    source: str
    provider_created_at: datetime
    applied_at: datetime


class PurchaseRepository:
    """Separates unattributed revenue from verified fan purchases."""

    ATTRIBUTED_SOURCES = {
        "provider_webhook",
        "provider_attributed",
    }

    def __init__(self, engine: Engine):
        self.engine = engine

    def ingest_wallet_transactions(
        self,
        creator_id: str,
        transactions: list[WalletTransaction],
    ) -> int:
        """Store the aggregate wallet ledger without inventing fan identity."""
        if not transactions:
            return 0
        now = utcnow()
        inserted = 0
        with self.engine.begin() as conn:
            self._ensure_creator(conn, creator_id, now)
            for row in transactions:
                exists_already = conn.execute(
                    select(
                        PROVIDER_WALLET_TRANSACTIONS.c.provider_transaction_id
                    ).where(
                        and_(
                            PROVIDER_WALLET_TRANSACTIONS.c.creator_id
                            == creator_id,
                            PROVIDER_WALLET_TRANSACTIONS.c.provider_transaction_id
                            == row.transaction_id,
                        )
                    )
                ).first()
                values = {
                    "creator_id": creator_id,
                    "provider_transaction_id": row.transaction_id,
                    "transaction_type": row.transaction_type,
                    "destination": row.destination,
                    "amount_millis": row.amount_millis,
                    "destination_tax_millis": (
                        row.destination_tax_millis
                    ),
                    "new_balance_millis": row.new_balance_millis,
                    "provider_created_at": self._provider_datetime(
                        row.created_at
                    ),
                    "provider_status": row.status,
                    "observed_at": now,
                }
                statement = self._insert(
                    PROVIDER_WALLET_TRANSACTIONS
                ).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=[
                        "creator_id",
                        "provider_transaction_id",
                    ],
                    set_={
                        "transaction_type": row.transaction_type,
                        "destination": row.destination,
                        "amount_millis": row.amount_millis,
                        "destination_tax_millis": (
                            row.destination_tax_millis
                        ),
                        "new_balance_millis": row.new_balance_millis,
                        "provider_status": row.status,
                        "observed_at": now,
                    },
                )
                conn.execute(statement)
                inserted += int(exists_already is None)
        return inserted

    def record_attributed_purchase(
        self,
        *,
        creator_id: str,
        provider_purchase_id: str,
        fan_id: str,
        provider_message_id: str,
        amount_millis: int,
        source: str,
        provider_created_at: datetime,
    ) -> tuple[PurchaseEventRecord, bool]:
        """Apply one purchase to its exact sent PPV, once.

        Aggregate wallet entries cannot call this method because they do not
        identify a fan or purchased provider message.
        """
        if source not in self.ATTRIBUTED_SOURCES:
            raise ValueError("purchase source is not attributable")
        if not provider_purchase_id.strip():
            raise ValueError("provider_purchase_id is required")
        if not provider_message_id.strip():
            raise ValueError("provider_message_id is required")
        if amount_millis <= 0:
            raise ValueError("amount_millis must be positive")
        if provider_created_at.tzinfo is None:
            provider_created_at = provider_created_at.replace(
                tzinfo=timezone.utc
            )
        now = utcnow()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(PURCHASE_EVENTS).where(
                    and_(
                        PURCHASE_EVENTS.c.creator_id == creator_id,
                        PURCHASE_EVENTS.c.provider_purchase_id
                        == provider_purchase_id,
                    )
                )
            ).mappings().first()
            if existing is not None:
                if (
                    existing["fan_id"] != fan_id
                    or existing["provider_message_id"]
                    != provider_message_id
                    or existing["amount_millis"] != amount_millis
                ):
                    raise ValueError(
                        "provider purchase ID conflicts with existing event"
                    )
                return self._event(existing), False

            outbox = conn.execute(
                select(OUTBOX_MESSAGES)
                .where(
                    and_(
                        OUTBOX_MESSAGES.c.creator_id == creator_id,
                        OUTBOX_MESSAGES.c.fan_id == fan_id,
                        OUTBOX_MESSAGES.c.provider_message_id
                        == provider_message_id,
                    )
                )
                .with_for_update()
            ).mappings().first()
            if outbox is None:
                raise ValueError("purchase does not match a sent outbox row")
            if outbox["status"] != OUTBOX_SENT:
                raise ValueError("purchase outbox is not sent")
            if outbox["message_kind"] != "ppv":
                raise ValueError("purchase outbox is not PPV")
            if outbox["price_millis"] != amount_millis:
                raise ValueError("purchase amount does not match PPV price")
            if (
                outbox["sequence_id"] is None
                or outbox["sequence_step_id"] is None
            ):
                raise ValueError("PPV outbox lacks sequence provenance")

            # A concurrent worker may have committed the same purchase while
            # this transaction waited for the outbox row lock.
            existing = conn.execute(
                select(PURCHASE_EVENTS).where(
                    and_(
                        PURCHASE_EVENTS.c.creator_id == creator_id,
                        PURCHASE_EVENTS.c.provider_purchase_id
                        == provider_purchase_id,
                    )
                )
            ).mappings().first()
            if existing is not None:
                if (
                    existing["fan_id"] != fan_id
                    or existing["provider_message_id"]
                    != provider_message_id
                    or existing["amount_millis"] != amount_millis
                ):
                    raise ValueError(
                        "provider purchase ID conflicts with existing event"
                    )
                return self._event(existing), False

            progress = conn.execute(
                select(PROGRESS_TABLE)
                .where(
                    and_(
                        PROGRESS_TABLE.c.creator_id == creator_id,
                        PROGRESS_TABLE.c.fan_id == fan_id,
                        PROGRESS_TABLE.c.sequence_id
                        == outbox["sequence_id"],
                    )
                )
                .with_for_update()
            ).mappings().first()
            step = conn.execute(
                select(STEPS_TABLE).where(
                    and_(
                        STEPS_TABLE.c.id
                        == outbox["sequence_step_id"],
                        STEPS_TABLE.c.sequence_id
                        == outbox["sequence_id"],
                    )
                )
            ).mappings().first()
            if progress is None or step is None:
                raise ValueError("PPV sequence progress is missing")
            if progress["status"] != StepStatus.SENT.value:
                raise ValueError("PPV sequence is not awaiting purchase")
            if progress["current_step"] != step["position"] + 1:
                raise ValueError("purchase does not match current PPV step")

            purchase = self._insert(PURCHASE_EVENTS).values(
                creator_id=creator_id,
                provider_purchase_id=provider_purchase_id,
                fan_id=fan_id,
                outbox_message_id=outbox["id"],
                provider_message_id=provider_message_id,
                amount_millis=amount_millis,
                source=source,
                provider_created_at=provider_created_at,
                applied_at=now,
            )
            purchase = purchase.on_conflict_do_nothing(
                index_elements=[
                    "creator_id",
                    "provider_purchase_id",
                ]
            )
            result = conn.execute(purchase)
            if result.rowcount != 1:
                existing = conn.execute(
                    select(PURCHASE_EVENTS).where(
                        and_(
                            PURCHASE_EVENTS.c.creator_id == creator_id,
                            PURCHASE_EVENTS.c.provider_purchase_id
                            == provider_purchase_id,
                        )
                    )
                ).mappings().one()
                return self._event(existing), False
            purchase_id = result.inserted_primary_key[0]

            next_step = conn.execute(
                select(STEPS_TABLE.c.id).where(
                    and_(
                        STEPS_TABLE.c.sequence_id
                        == outbox["sequence_id"],
                        STEPS_TABLE.c.position == step["position"] + 1,
                    )
                )
            ).first()
            conn.execute(
                update(PROGRESS_TABLE)
                .where(PROGRESS_TABLE.c.id == progress["id"])
                .values(
                    current_step=(
                        progress["current_step"]
                        if next_step
                        else 0
                    ),
                    status=(
                        StepStatus.PENDING.value
                        if next_step
                        else StepStatus.BOUGHT.value
                    ),
                    bought_at=provider_created_at,
                )
            )
            self._update_fan_state(
                conn,
                creator_id=creator_id,
                fan_id=fan_id,
                amount_millis=amount_millis,
                purchased_at=provider_created_at,
            )
            created = conn.execute(
                select(PURCHASE_EVENTS).where(
                    PURCHASE_EVENTS.c.id == purchase_id
                )
            ).mappings().one()
        return self._event(created), True

    def count_wallet_transactions(self, creator_id: str) -> int:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    PROVIDER_WALLET_TRANSACTIONS.c.provider_transaction_id
                ).where(
                    PROVIDER_WALLET_TRANSACTIONS.c.creator_id == creator_id
                )
            ).all()
        return len(rows)

    def count_purchase_events(self, creator_id: str) -> int:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(PURCHASE_EVENTS.c.id).where(
                    PURCHASE_EVENTS.c.creator_id == creator_id
                )
            ).all()
        return len(rows)

    def _update_fan_state(
        self,
        conn,
        *,
        creator_id: str,
        fan_id: str,
        amount_millis: int,
        purchased_at: datetime,
    ) -> None:
        note = conn.execute(
            select(FAN_NOTES_TABLE).where(
                and_(
                    FAN_NOTES_TABLE.c.creator_id == creator_id,
                    FAN_NOTES_TABLE.c.fan_id == fan_id,
                )
            )
        ).mappings().first()
        if note is None:
            raise ValueError("fan note is missing")
        conn.execute(
            update(FAN_NOTES_TABLE)
            .where(
                and_(
                    FAN_NOTES_TABLE.c.creator_id == creator_id,
                    FAN_NOTES_TABLE.c.fan_id == fan_id,
                )
            )
            .values(
                total_spent=FAN_NOTES_TABLE.c.total_spent
                + amount_millis / 1000,
                purchase_count=FAN_NOTES_TABLE.c.purchase_count + 1,
                last_purchase_at=purchased_at,
            )
        )
        runtime_update = conn.execute(
            update(FAN_RUNTIME_STATES)
            .where(
                and_(
                    FAN_RUNTIME_STATES.c.creator_id == creator_id,
                    FAN_RUNTIME_STATES.c.fan_id == fan_id,
                )
            )
            .values(
                escalation_level=(
                    FAN_RUNTIME_STATES.c.escalation_level + 1
                ),
                ppvs_bought=FAN_RUNTIME_STATES.c.ppvs_bought + 1,
                consecutive_rejections=0,
                purchase_count_seen=(
                    FAN_RUNTIME_STATES.c.purchase_count_seen + 1
                ),
                version=FAN_RUNTIME_STATES.c.version + 1,
                updated_at=utcnow(),
            )
        )
        if runtime_update.rowcount != 1:
            raise ValueError("durable fan runtime state is missing")

    def _ensure_creator(
        self,
        conn,
        creator_id: str,
        now: datetime,
    ) -> None:
        statement = self._insert(CREATORS).values(
            id=creator_id,
            created_at=now,
            updated_at=now,
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=["id"],
                set_={"updated_at": now},
            )
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
    def _provider_datetime(timestamp: float) -> datetime:
        numeric = float(timestamp or 0)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return datetime.fromtimestamp(numeric, timezone.utc)

    @staticmethod
    def _event(row) -> PurchaseEventRecord:
        return PurchaseEventRecord(
            id=row["id"],
            creator_id=row["creator_id"],
            provider_purchase_id=row["provider_purchase_id"],
            fan_id=row["fan_id"],
            outbox_message_id=row["outbox_message_id"],
            provider_message_id=row["provider_message_id"],
            amount_millis=row["amount_millis"],
            source=row["source"],
            provider_created_at=row["provider_created_at"],
            applied_at=row["applied_at"],
        )
