"""Canonical read models for the operator dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, and_, func, or_, select

from src.notes.repository import FAN_NOTES_TABLE

from .schema import (
    CONVERSATIONS,
    CRM_CHAT_SYNC,
    FANS,
    FAN_MESSAGES,
    FAN_RUNTIME_STATES,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    PROVIDER_WALLET_TRANSACTIONS,
    PURCHASE_EVENTS,
)


@dataclass(frozen=True)
class FanPurchaseTotals:
    fan_id: str
    purchase_count: int
    total_spent_millis: int
    last_purchase_at: datetime | None


@dataclass(frozen=True)
class DashboardMetrics:
    known_fans: int
    completed_inbounds: int
    sent_outbounds: int
    text_sends: int
    media_sends: int
    ppv_sends: int
    blocked_ppv_intents: int
    delivery_unknown: int
    attributed_purchases: int
    attributed_revenue_millis: int
    average_order_value_millis: int | None
    ppv_unlock_rate: float | None
    average_response_seconds: float | None
    wallet_transactions: int
    wallet_latest_balance_millis: int | None


@dataclass(frozen=True)
class DurableConversationSummary:
    fan_id: str
    display_name: str | None
    username: str | None
    avatar_url: str | None
    phase: str
    escalation_level: int
    cooldown: bool
    message_count: int
    last_activity_at: datetime | None
    history_complete: bool
    sync_error: str | None


@dataclass(frozen=True)
class ConversationPage:
    conversations: list[DurableConversationSummary]
    total: int
    limit: int
    offset: int
    has_more: bool


class DashboardReadRepository:
    """Build dashboard values only from durable, attributable records."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def fan_purchase_totals(
        self,
        creator_id: str,
    ) -> dict[str, FanPurchaseTotals]:
        statement = (
            select(
                PURCHASE_EVENTS.c.fan_id,
                func.count(PURCHASE_EVENTS.c.id).label("purchase_count"),
                func.coalesce(
                    func.sum(PURCHASE_EVENTS.c.amount_millis),
                    0,
                ).label("total_spent_millis"),
                func.max(PURCHASE_EVENTS.c.provider_created_at).label(
                    "last_purchase_at"
                ),
            )
            .where(PURCHASE_EVENTS.c.creator_id == creator_id)
            .group_by(PURCHASE_EVENTS.c.fan_id)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(statement).mappings().all()
        return {
            row["fan_id"]: FanPurchaseTotals(
                fan_id=row["fan_id"],
                purchase_count=int(row["purchase_count"] or 0),
                total_spent_millis=int(
                    row["total_spent_millis"] or 0
                ),
                last_purchase_at=row["last_purchase_at"],
            )
            for row in rows
        }

    def conversations(
        self,
        creator_id: str,
    ) -> list[DurableConversationSummary]:
        return self.conversation_page(
            creator_id,
            limit=100_000,
        ).conversations

    def conversation_page(
        self,
        creator_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        search: str | None = None,
    ) -> ConversationPage:
        limit = min(max(int(limit), 1), 100_000)
        offset = max(int(offset), 0)
        message_totals = (
            select(
                FAN_MESSAGES.c.fan_id.label("fan_id"),
                func.count(FAN_MESSAGES.c.id).label("stored_message_count"),
                func.max(FAN_MESSAGES.c.created_at).label(
                    "stored_last_activity_at"
                ),
            )
            .where(FAN_MESSAGES.c.creator_id == creator_id)
            .group_by(FAN_MESSAGES.c.fan_id)
            .subquery("crm_message_totals")
        )
        fan_runtime_join = FANS.outerjoin(
            FAN_RUNTIME_STATES,
            and_(
                FANS.c.creator_id
                == FAN_RUNTIME_STATES.c.creator_id,
                FANS.c.fan_id == FAN_RUNTIME_STATES.c.fan_id,
            ),
        ).outerjoin(
            CONVERSATIONS,
            and_(
                FANS.c.creator_id == CONVERSATIONS.c.creator_id,
                FANS.c.fan_id == CONVERSATIONS.c.fan_id,
            ),
        ).outerjoin(
            CRM_CHAT_SYNC,
            and_(
                CONVERSATIONS.c.creator_id
                == CRM_CHAT_SYNC.c.creator_id,
                CONVERSATIONS.c.chat_id == CRM_CHAT_SYNC.c.chat_id,
            ),
        ).outerjoin(
            message_totals,
            FANS.c.fan_id == message_totals.c.fan_id,
        )
        predicates = [FANS.c.creator_id == creator_id]
        normalized_search = str(search or "").strip().lower()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            predicates.append(
                or_(
                    func.lower(
                        func.coalesce(FANS.c.display_name, "")
                    ).like(pattern),
                    func.lower(
                        func.coalesce(FANS.c.username, "")
                    ).like(pattern),
                    func.lower(FANS.c.fan_id).like(pattern),
                )
            )
        last_activity = func.coalesce(
            message_totals.c.stored_last_activity_at,
            FAN_RUNTIME_STATES.c.last_activity_at,
            CONVERSATIONS.c.last_activity_at,
        )
        statement = (
            select(
                FANS.c.fan_id,
                FANS.c.display_name,
                FANS.c.username,
                FANS.c.avatar_url,
                FAN_RUNTIME_STATES.c.phase,
                FAN_RUNTIME_STATES.c.escalation_level,
                FAN_RUNTIME_STATES.c.cooldown,
                func.coalesce(
                    message_totals.c.stored_message_count,
                    0,
                ).label("message_count"),
                last_activity.label("last_activity_at"),
                CRM_CHAT_SYNC.c.history_complete,
                CRM_CHAT_SYNC.c.last_error,
            )
            .select_from(fan_runtime_join)
            .where(and_(*predicates))
            .order_by(
                last_activity.desc(),
                FANS.c.fan_id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        count_statement = (
            select(func.count())
            .select_from(fan_runtime_join)
            .where(and_(*predicates))
        )
        with self.engine.connect() as conn:
            total = int(
                conn.execute(count_statement).scalar_one() or 0
            )
            rows = conn.execute(statement).mappings().all()
        conversations = [
            DurableConversationSummary(
                fan_id=row["fan_id"],
                display_name=row["display_name"],
                username=row["username"],
                avatar_url=row["avatar_url"],
                phase=row["phase"] or "rapport",
                escalation_level=int(
                    row["escalation_level"] or 0
                ),
                cooldown=bool(row["cooldown"]),
                message_count=int(row["message_count"] or 0),
                last_activity_at=row["last_activity_at"],
                history_complete=bool(row["history_complete"]),
                sync_error=row["last_error"],
            )
            for row in rows
        ]
        return ConversationPage(
            conversations=conversations,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(conversations) < total,
        )

    def metrics(self, creator_id: str) -> DashboardMetrics:
        with self.engine.connect() as conn:
            durable_fans = {
                row[0]
                for row in conn.execute(
                    select(FANS.c.fan_id).where(
                        FANS.c.creator_id == creator_id
                    )
                )
            }
            note_fans = {
                row[0]
                for row in conn.execute(
                    select(FAN_NOTES_TABLE.c.fan_id).where(
                        FAN_NOTES_TABLE.c.creator_id == creator_id
                    )
                )
            }
            completed_inbounds = self._count(
                conn,
                INBOUND_MESSAGES,
                and_(
                    INBOUND_MESSAGES.c.creator_id == creator_id,
                    INBOUND_MESSAGES.c.status == "completed",
                ),
            )
            sent_outbounds = self._count(
                conn,
                OUTBOX_MESSAGES,
                and_(
                    OUTBOX_MESSAGES.c.creator_id == creator_id,
                    OUTBOX_MESSAGES.c.status == "sent",
                ),
            )
            text_sends = self._sent_kind(
                conn,
                creator_id,
                "text",
            )
            media_sends = self._sent_kind(
                conn,
                creator_id,
                "media",
            )
            ppv_sends = self._sent_kind(
                conn,
                creator_id,
                "ppv",
            )
            blocked_ppv_intents = self._count(
                conn,
                OUTBOX_MESSAGES,
                and_(
                    OUTBOX_MESSAGES.c.creator_id == creator_id,
                    OUTBOX_MESSAGES.c.message_kind == "ppv",
                    OUTBOX_MESSAGES.c.status
                    == "blocked_unsupported",
                ),
            )
            delivery_unknown = self._count(
                conn,
                OUTBOX_MESSAGES,
                and_(
                    OUTBOX_MESSAGES.c.creator_id == creator_id,
                    OUTBOX_MESSAGES.c.status == "delivery_unknown",
                ),
            )
            attributed_purchases = self._count(
                conn,
                PURCHASE_EVENTS,
                PURCHASE_EVENTS.c.creator_id == creator_id,
            )
            attributed_revenue_millis = int(
                conn.execute(
                    select(
                        func.coalesce(
                            func.sum(PURCHASE_EVENTS.c.amount_millis),
                            0,
                        )
                    ).where(PURCHASE_EVENTS.c.creator_id == creator_id)
                ).scalar_one()
                or 0
            )
            wallet_transactions = self._count(
                conn,
                PROVIDER_WALLET_TRANSACTIONS,
                PROVIDER_WALLET_TRANSACTIONS.c.creator_id
                == creator_id,
            )
            wallet_latest_balance = conn.execute(
                select(
                    PROVIDER_WALLET_TRANSACTIONS.c.new_balance_millis
                )
                .where(
                    PROVIDER_WALLET_TRANSACTIONS.c.creator_id
                    == creator_id
                )
                .order_by(
                    PROVIDER_WALLET_TRANSACTIONS.c.provider_created_at.desc(),
                    PROVIDER_WALLET_TRANSACTIONS.c.provider_transaction_id.desc(),
                )
                .limit(1)
            ).scalar_one_or_none()
            response_rows = conn.execute(
                select(
                    INBOUND_MESSAGES.c.provider_created_at,
                    OUTBOX_MESSAGES.c.sent_at,
                )
                .select_from(
                    OUTBOX_MESSAGES.join(
                        INBOUND_MESSAGES,
                        OUTBOX_MESSAGES.c.inbound_message_id
                        == INBOUND_MESSAGES.c.id,
                    )
                )
                .where(
                    and_(
                        OUTBOX_MESSAGES.c.creator_id == creator_id,
                        OUTBOX_MESSAGES.c.status == "sent",
                        OUTBOX_MESSAGES.c.sent_at.is_not(None),
                    )
                )
            ).all()

        response_seconds = [
            delta
            for provider_created_at, sent_at in response_rows
            if (
                delta := self._seconds_between(
                    provider_created_at,
                    sent_at,
                )
            )
            >= 0
        ]
        return DashboardMetrics(
            known_fans=len(durable_fans | note_fans),
            completed_inbounds=completed_inbounds,
            sent_outbounds=sent_outbounds,
            text_sends=text_sends,
            media_sends=media_sends,
            ppv_sends=ppv_sends,
            blocked_ppv_intents=blocked_ppv_intents,
            delivery_unknown=delivery_unknown,
            attributed_purchases=attributed_purchases,
            attributed_revenue_millis=attributed_revenue_millis,
            average_order_value_millis=(
                round(
                    attributed_revenue_millis
                    / attributed_purchases
                )
                if attributed_purchases
                else None
            ),
            ppv_unlock_rate=(
                attributed_purchases / ppv_sends * 100
                if ppv_sends
                else None
            ),
            average_response_seconds=(
                sum(response_seconds) / len(response_seconds)
                if response_seconds
                else None
            ),
            wallet_transactions=wallet_transactions,
            wallet_latest_balance_millis=(
                int(wallet_latest_balance)
                if wallet_latest_balance is not None
                else None
            ),
        )

    @staticmethod
    def _count(conn, table, predicate) -> int:
        return int(
            conn.execute(
                select(func.count()).select_from(table).where(predicate)
            ).scalar_one()
            or 0
        )

    @staticmethod
    def _sent_kind(conn, creator_id: str, message_kind: str) -> int:
        return DashboardReadRepository._count(
            conn,
            OUTBOX_MESSAGES,
            and_(
                OUTBOX_MESSAGES.c.creator_id == creator_id,
                OUTBOX_MESSAGES.c.status == "sent",
                OUTBOX_MESSAGES.c.message_kind == message_kind,
            ),
        )

    @staticmethod
    def _seconds_between(
        started_at: datetime,
        completed_at: datetime,
    ) -> float:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        return (completed_at - started_at).total_seconds()
