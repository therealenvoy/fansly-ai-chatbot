"""Durable fan-presence observations and proactive outreach limits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, and_, desc, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .schema import (
    CONVERSATIONS,
    CRM_CHAT_SYNC,
    FAN_MESSAGES,
    FAN_CONTACT_POLICIES,
    FAN_PRESENCE,
    FANS,
    INBOUND_MESSAGES,
    OUTBOX_MESSAGES,
    utcnow,
)


@dataclass(frozen=True)
class PresenceCandidate:
    fan_id: str
    chat_id: str
    username: str | None
    display_name: str | None


@dataclass(frozen=True)
class PresenceObservation:
    fan_id: str
    status: str
    previous_status: str
    first_observation: bool
    transitioned_online: bool
    last_seen_at: datetime | None


@dataclass(frozen=True)
class StalledConversationCandidate:
    fan_id: str
    chat_id: str
    latest_creator_message_id: str | None
    latest_creator_message_at: datetime
    latest_fan_message_id: str | None
    latest_fan_message_at: datetime | None

    @property
    def episode_key(self) -> str:
        if self.latest_fan_message_id:
            return self.latest_fan_message_id
        if self.latest_fan_message_at:
            return self.latest_fan_message_at.isoformat()
        return "no-fan-message"


class PresenceRepository:
    """Own online transition state and outreach cooldown accounting."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def candidates(
        self,
        creator_id: str,
        *,
        allowed_fan_ids: set[str] | None = None,
        limit: int = 500,
    ) -> list[PresenceCandidate]:
        statement = (
            select(
                FANS.c.fan_id,
                CONVERSATIONS.c.chat_id,
                FANS.c.username,
                FANS.c.display_name,
            )
            .select_from(
                FANS.join(
                    CONVERSATIONS,
                    and_(
                        FANS.c.creator_id == CONVERSATIONS.c.creator_id,
                        FANS.c.fan_id == CONVERSATIONS.c.fan_id,
                    ),
                )
            )
            .where(FANS.c.creator_id == creator_id)
            .order_by(CONVERSATIONS.c.updated_at.desc())
            .limit(min(max(int(limit), 1), 5000))
        )
        if allowed_fan_ids is not None:
            normalized = tuple(sorted(str(item) for item in allowed_fan_ids))
            if not normalized:
                return []
            statement = statement.where(FANS.c.fan_id.in_(normalized))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            PresenceCandidate(
                fan_id=str(row["fan_id"]),
                chat_id=str(row["chat_id"]),
                username=row["username"],
                display_name=row["display_name"],
            )
            for row in rows
        ]

    def observe(
        self,
        *,
        creator_id: str,
        fan_id: str,
        last_seen_at: datetime | None,
        provider_status_id: int | None,
        observed_at: datetime,
        online_window_seconds: int,
    ) -> PresenceObservation:
        observed_at = self._aware(observed_at)
        last_seen_at = (
            self._aware(last_seen_at)
            if last_seen_at is not None
            else None
        )
        threshold = observed_at - timedelta(
            seconds=max(1, int(online_window_seconds))
        )
        status = (
            "online"
            if last_seen_at is not None and last_seen_at >= threshold
            else "offline"
        )
        now = utcnow()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(FAN_PRESENCE)
                .where(
                    and_(
                        FAN_PRESENCE.c.creator_id == creator_id,
                        FAN_PRESENCE.c.fan_id == fan_id,
                    )
                )
                .with_for_update()
            ).mappings().first()
            previous = (
                str(existing["status"]) if existing is not None else "unknown"
            )
            first = existing is None
            transitioned = previous == "offline" and status == "online"
            online_since = (
                observed_at
                if status == "online" and previous != "online"
                else (
                    existing["online_since"]
                    if existing is not None and status == "online"
                    else None
                )
            )
            transition_at = (
                observed_at
                if previous != status
                else (
                    existing["last_transition_at"]
                    if existing is not None
                    else observed_at
                )
            )
            values = {
                "creator_id": creator_id,
                "fan_id": fan_id,
                "status": status,
                "provider_status_id": provider_status_id,
                "last_seen_at": last_seen_at,
                "observed_at": observed_at,
                "online_since": online_since,
                "last_transition_at": transition_at,
                "created_at": now,
                "updated_at": now,
            }
            statement = self._insert(FAN_PRESENCE).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=["creator_id", "fan_id"],
                set_={
                    key: value
                    for key, value in values.items()
                    if key not in {"creator_id", "fan_id", "created_at"}
                },
            )
            connection.execute(statement)
        return PresenceObservation(
            fan_id=fan_id,
            status=status,
            previous_status=previous,
            first_observation=first,
            transitioned_online=transitioned,
            last_seen_at=last_seen_at,
        )

    def eligible_for_outreach(
        self,
        *,
        creator_id: str,
        fan_id: str,
        now: datetime,
        trigger_kind: str = "online",
        require_online: bool = True,
        cooldown_hours: int,
        max_per_hour: int,
        max_per_day: int,
        max_per_fan_per_day: int,
    ) -> tuple[bool, str | None]:
        if trigger_kind not in {"online", "stalled"}:
            return False, "unsupported proactive trigger"
        now = self._aware(now)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        fan_cooldown = now - timedelta(hours=max(1, cooldown_hours))
        proactive_triggers = ("online", "stalled")
        sent_base = (
            select(func.count(OUTBOX_MESSAGES.c.id))
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
                    INBOUND_MESSAGES.c.trigger_kind.in_(
                        proactive_triggers
                    ),
                )
            )
        )
        pending_base = select(func.count(INBOUND_MESSAGES.c.id)).where(
            and_(
                INBOUND_MESSAGES.c.creator_id == creator_id,
                INBOUND_MESSAGES.c.trigger_kind.in_(
                    proactive_triggers
                ),
                INBOUND_MESSAGES.c.status.in_(["pending", "processing"]),
            )
        )
        with self.engine.connect() as connection:
            presence = connection.execute(
                select(FAN_PRESENCE).where(
                    and_(
                        FAN_PRESENCE.c.creator_id == creator_id,
                        FAN_PRESENCE.c.fan_id == fan_id,
                    )
                )
            ).mappings().first()
            if require_online and (
                presence is None or presence["status"] != "online"
            ):
                return False, "fan is not currently online"
            policy = connection.execute(
                select(FAN_CONTACT_POLICIES).where(
                    and_(
                        FAN_CONTACT_POLICIES.c.creator_id == creator_id,
                        FAN_CONTACT_POLICIES.c.fan_id == fan_id,
                    )
                )
            ).mappings().first()
            if policy is not None:
                if bool(policy["do_not_contact"]):
                    return False, "fan opted out"
                if (
                    policy["paused_until"] is not None
                    and self._aware(policy["paused_until"]) > now
                ):
                    return False, "fan contact is paused"
                if (
                    policy["cooldown_until"] is not None
                    and self._aware(policy["cooldown_until"]) > now
                ):
                    return False, "fan contact policy cooldown is active"

            last_outreach = connection.execute(
                select(func.max(OUTBOX_MESSAGES.c.sent_at))
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
                        OUTBOX_MESSAGES.c.fan_id == fan_id,
                        OUTBOX_MESSAGES.c.status == "sent",
                        INBOUND_MESSAGES.c.trigger_kind.in_(
                            proactive_triggers
                        ),
                    )
                )
            ).scalar_one_or_none()
            if (
                last_outreach is not None
                and self._aware(last_outreach) > fan_cooldown
            ):
                return False, "fan is in proactive cooldown"

            pending = connection.execute(
                select(func.count(INBOUND_MESSAGES.c.id)).where(
                    and_(
                        INBOUND_MESSAGES.c.creator_id == creator_id,
                        INBOUND_MESSAGES.c.fan_id == fan_id,
                        INBOUND_MESSAGES.c.status.in_(
                            ["pending", "processing"]
                        ),
                    )
                )
            ).scalar_one()
            if int(pending or 0):
                return False, "fan already has pending conversation work"

            latest = connection.execute(
                select(
                    FAN_MESSAGES.c.sender,
                    FAN_MESSAGES.c.created_at,
                )
                .where(
                    and_(
                        FAN_MESSAGES.c.creator_id == creator_id,
                        FAN_MESSAGES.c.fan_id == fan_id,
                    )
                )
                .order_by(
                    desc(FAN_MESSAGES.c.created_at),
                    desc(FAN_MESSAGES.c.id),
                )
                .limit(1)
            ).first()
            if (
                latest is not None
                and latest.sender == "creator"
                and latest.created_at is not None
                and self._aware(latest.created_at) > fan_cooldown
            ):
                return False, "creator sent the latest recent message"

            if max_per_hour > 0:
                sent_hour = connection.execute(
                    sent_base.where(OUTBOX_MESSAGES.c.sent_at >= hour_ago)
                ).scalar_one()
                pending_hour = connection.execute(
                    pending_base.where(
                        INBOUND_MESSAGES.c.provider_created_at >= hour_ago
                    )
                ).scalar_one()
                if int(sent_hour or 0) + int(pending_hour or 0) >= max_per_hour:
                    return False, "hourly proactive limit reached"

            if max_per_day > 0:
                sent_day = connection.execute(
                    sent_base.where(OUTBOX_MESSAGES.c.sent_at >= day_ago)
                ).scalar_one()
                pending_day = connection.execute(
                    pending_base.where(
                        INBOUND_MESSAGES.c.provider_created_at >= day_ago
                    )
                ).scalar_one()
                if int(sent_day or 0) + int(pending_day or 0) >= max_per_day:
                    return False, "daily proactive limit reached"

            if max_per_fan_per_day > 0:
                sent_fan_day = connection.execute(
                    sent_base.where(
                        and_(
                            OUTBOX_MESSAGES.c.sent_at >= day_ago,
                            OUTBOX_MESSAGES.c.fan_id == fan_id,
                        )
                    )
                ).scalar_one()
                pending_fan_day = connection.execute(
                    pending_base.where(
                        and_(
                            INBOUND_MESSAGES.c.provider_created_at >= day_ago,
                            INBOUND_MESSAGES.c.fan_id == fan_id,
                        )
                    )
                ).scalar_one()
                if (
                    int(sent_fan_day or 0)
                    + int(pending_fan_day or 0)
                    >= max_per_fan_per_day
                ):
                    return False, "fan daily proactive limit reached"
        return True, None

    def stalled_candidates(
        self,
        creator_id: str,
        *,
        stalled_before: datetime,
        allowed_fan_ids: set[str] | None = None,
        limit: int = 5000,
    ) -> list[StalledConversationCandidate]:
        """Return chats whose latest fully-synced message is an old creator send."""
        stalled_before = self._aware(stalled_before)
        rank = func.row_number().over(
            partition_by=FAN_MESSAGES.c.fan_id,
            order_by=(
                FAN_MESSAGES.c.created_at.desc(),
                FAN_MESSAGES.c.id.desc(),
            ),
        )
        latest_messages = (
            select(
                FAN_MESSAGES.c.fan_id.label("fan_id"),
                FAN_MESSAGES.c.sender.label("sender"),
                FAN_MESSAGES.c.message_id.label("message_id"),
                FAN_MESSAGES.c.created_at.label("created_at"),
                rank.label("message_rank"),
            )
            .where(FAN_MESSAGES.c.creator_id == creator_id)
            .subquery("latest_messages")
        )
        latest_fan_messages = (
            select(
                FAN_MESSAGES.c.fan_id.label("fan_id"),
                FAN_MESSAGES.c.message_id.label("message_id"),
                FAN_MESSAGES.c.created_at.label("created_at"),
                func.row_number()
                .over(
                    partition_by=FAN_MESSAGES.c.fan_id,
                    order_by=(
                        FAN_MESSAGES.c.created_at.desc(),
                        FAN_MESSAGES.c.id.desc(),
                    ),
                )
                .label("message_rank"),
            )
            .where(
                and_(
                    FAN_MESSAGES.c.creator_id == creator_id,
                    FAN_MESSAGES.c.sender == "fan",
                )
            )
            .subquery("latest_fan_messages")
        )
        pending_for_fan = exists(
            select(INBOUND_MESSAGES.c.id).where(
                and_(
                    INBOUND_MESSAGES.c.creator_id == creator_id,
                    INBOUND_MESSAGES.c.fan_id == CONVERSATIONS.c.fan_id,
                    INBOUND_MESSAGES.c.status.in_(
                        ["pending", "processing"]
                    ),
                )
            )
        )
        statement = (
            select(
                CONVERSATIONS.c.fan_id,
                CONVERSATIONS.c.chat_id,
                latest_messages.c.message_id.label(
                    "latest_creator_message_id"
                ),
                latest_messages.c.created_at.label(
                    "latest_creator_message_at"
                ),
                latest_fan_messages.c.message_id.label(
                    "latest_fan_message_id"
                ),
                latest_fan_messages.c.created_at.label(
                    "latest_fan_message_at"
                ),
            )
            .select_from(
                CONVERSATIONS.join(
                    latest_messages,
                    and_(
                        CONVERSATIONS.c.fan_id
                        == latest_messages.c.fan_id,
                        latest_messages.c.message_rank == 1,
                    ),
                )
                .outerjoin(
                    latest_fan_messages,
                    and_(
                        CONVERSATIONS.c.fan_id
                        == latest_fan_messages.c.fan_id,
                        latest_fan_messages.c.message_rank == 1,
                    ),
                )
                .join(
                    CRM_CHAT_SYNC,
                    and_(
                        CONVERSATIONS.c.creator_id
                        == CRM_CHAT_SYNC.c.creator_id,
                        CONVERSATIONS.c.chat_id
                        == CRM_CHAT_SYNC.c.chat_id,
                    ),
                )
            )
            .where(
                and_(
                    CONVERSATIONS.c.creator_id == creator_id,
                    latest_messages.c.sender == "creator",
                    latest_messages.c.created_at <= stalled_before,
                    CRM_CHAT_SYNC.c.provider_head_message_id
                    == CRM_CHAT_SYNC.c.stored_head_message_id,
                    ~pending_for_fan,
                )
            )
            .order_by(
                latest_messages.c.created_at.asc(),
                CONVERSATIONS.c.fan_id.asc(),
            )
            .limit(min(max(int(limit), 1), 5000))
        )
        if allowed_fan_ids is not None:
            normalized = tuple(
                sorted(str(item) for item in allowed_fan_ids)
            )
            if not normalized:
                return []
            statement = statement.where(
                CONVERSATIONS.c.fan_id.in_(normalized)
            )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            StalledConversationCandidate(
                fan_id=str(row["fan_id"]),
                chat_id=str(row["chat_id"]),
                latest_creator_message_id=row[
                    "latest_creator_message_id"
                ],
                latest_creator_message_at=self._aware(
                    row["latest_creator_message_at"]
                ),
                latest_fan_message_id=row["latest_fan_message_id"],
                latest_fan_message_at=(
                    self._aware(row["latest_fan_message_at"])
                    if row["latest_fan_message_at"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def mark_outreach_sent(
        self,
        creator_id: str,
        fan_id: str,
        *,
        sent_at: datetime | None = None,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(FAN_PRESENCE)
                .where(
                    and_(
                        FAN_PRESENCE.c.creator_id == creator_id,
                        FAN_PRESENCE.c.fan_id == fan_id,
                    )
                )
                .values(
                    last_outreach_at=sent_at or utcnow(),
                    updated_at=utcnow(),
                )
            )

    def for_fans(
        self,
        creator_id: str,
        fan_ids: list[str],
    ) -> dict[str, dict]:
        if not fan_ids:
            return {}
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(FAN_PRESENCE).where(
                    and_(
                        FAN_PRESENCE.c.creator_id == creator_id,
                        FAN_PRESENCE.c.fan_id.in_(fan_ids),
                    )
                )
            ).mappings().all()
        return {
            str(row["fan_id"]): {
                "presence": str(row["status"]),
                "last_seen_at": (
                    row["last_seen_at"].isoformat()
                    if row["last_seen_at"]
                    else None
                ),
                "last_outreach_at": (
                    row["last_outreach_at"].isoformat()
                    if row["last_outreach_at"]
                    else None
                ),
            }
            for row in rows
        }

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
