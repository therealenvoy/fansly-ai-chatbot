"""Truthful native planning, exclusive trigger ownership, and contact claims."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import Engine, and_, desc, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.persistence.schema import (
    CONTACT_CLAIMS,
    NATIVE_AUTOMATIONS,
    NATIVE_CAMPAIGNS,
    TRIGGER_OWNERSHIP,
    TRIGGER_OWNERSHIP_EVENTS,
)


class TriggerType(str, Enum):
    NEW_FOLLOWER = "new_follower"
    NEW_SUBSCRIBER = "new_subscriber"
    GIFT_SUBSCRIBER = "gift_subscriber"
    RENEWAL = "renewal"
    QUALIFYING_TIP = "qualifying_tip"
    ONLINE = "online"
    STALLED = "stalled"
    INBOUND_REPLY = "inbound_reply"


class TriggerOwner(str, Enum):
    FANSLY_NATIVE_AUTOMATION = "fansly_native_automation"
    FANSLY_NATIVE_MASS = "fansly_native_mass"
    CURRENT_BRAIN = "current_brain"
    BRAIN2 = "brain2"
    DISABLED = "disabled"


class OwnershipConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class Ownership:
    trigger_type: TriggerType
    owner: TriggerOwner
    version: int


class TriggerOwnershipRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, creator_id: str, trigger_type: TriggerType) -> Ownership | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(TRIGGER_OWNERSHIP).where(
                    and_(
                        TRIGGER_OWNERSHIP.c.creator_id == creator_id,
                        TRIGGER_OWNERSHIP.c.trigger_type == trigger_type.value,
                    )
                )
            ).mappings().first()
        if row is None:
            return None
        return Ownership(
            trigger_type=TriggerType(row["trigger_type"]),
            owner=TriggerOwner(row["owner"]),
            version=int(row["version"]),
        )

    def assign(
        self,
        creator_id: str,
        trigger_type: TriggerType,
        owner: TriggerOwner,
        *,
        actor: str,
        reason: str,
    ) -> Ownership:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(TRIGGER_OWNERSHIP)
                .where(
                    and_(
                        TRIGGER_OWNERSHIP.c.creator_id == creator_id,
                        TRIGGER_OWNERSHIP.c.trigger_type == trigger_type.value,
                    )
                )
                .with_for_update()
            ).mappings().first()
            previous = TriggerOwner(row["owner"]) if row else None
            if (
                previous is not None
                and previous != TriggerOwner.DISABLED
                and owner not in {previous, TriggerOwner.DISABLED}
            ):
                raise OwnershipConflict(
                    "disable the current trigger owner before assigning another"
                )
            version = int(row["version"]) + 1 if row else 1
            if row is None:
                connection.execute(
                    insert(TRIGGER_OWNERSHIP).values(
                        creator_id=creator_id,
                        trigger_type=trigger_type.value,
                        owner=owner.value,
                        version=version,
                        updated_by=actor[:64],
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(TRIGGER_OWNERSHIP)
                    .where(
                        and_(
                            TRIGGER_OWNERSHIP.c.creator_id == creator_id,
                            TRIGGER_OWNERSHIP.c.trigger_type == trigger_type.value,
                        )
                    )
                    .values(
                        owner=owner.value,
                        version=version,
                        updated_by=actor[:64],
                        updated_at=now,
                    )
                )
            connection.execute(
                insert(TRIGGER_OWNERSHIP_EVENTS).values(
                    creator_id=creator_id,
                    trigger_type=trigger_type.value,
                    previous_owner=previous.value if previous else None,
                    new_owner=owner.value,
                    actor=actor[:64],
                    reason=reason[:128],
                    created_at=now,
                )
            )
        return Ownership(trigger_type, owner, version)


@dataclass(frozen=True)
class ClaimResult:
    granted: bool
    claim_id: int
    denial_reason: str | None


class ContactClaimRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def key(
        creator_id: str,
        fan_id: str,
        trigger_type: TriggerType,
        trigger_event_id: str,
    ) -> str:
        return hashlib.sha256(
            "\0".join(
                (creator_id, fan_id, trigger_type.value, trigger_event_id)
            ).encode("utf-8")
        ).hexdigest()

    def claim(
        self,
        *,
        creator_id: str,
        fan_id: str,
        trigger_type: TriggerType,
        trigger_event_id: str,
        source_system: TriggerOwner,
        cooldown_seconds: int = 0,
        campaign_or_automation_id: str | None = None,
        outbox_id: int | None = None,
        native_message_hash: str | None = None,
    ) -> ClaimResult:
        now = datetime.now(timezone.utc)
        key = self.key(
            creator_id,
            fan_id,
            trigger_type,
            trigger_event_id,
        )
        values = {
            "creator_id": creator_id,
            "fan_id": fan_id,
            "trigger_type": trigger_type.value,
            "trigger_event_id": trigger_event_id,
            "source_system": source_system.value,
            "campaign_or_automation_id": campaign_or_automation_id,
            "idempotency_key": key,
            "claimed_at": now,
            "cooldown_until": (
                now + timedelta(seconds=max(0, cooldown_seconds))
                if cooldown_seconds
                else None
            ),
            "outbox_id": outbox_id,
            "native_message_hash": native_message_hash,
            "status": "claimed",
            "denial_reason": None,
        }
        statement = self._insert(CONTACT_CLAIMS).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=["creator_id", "idempotency_key"]
        )
        with self.engine.begin() as connection:
            created = connection.execute(statement).rowcount == 1
            row = connection.execute(
                select(CONTACT_CLAIMS).where(
                    and_(
                        CONTACT_CLAIMS.c.creator_id == creator_id,
                        CONTACT_CLAIMS.c.idempotency_key == key,
                    )
                )
            ).mappings().one()
        same_source = row["source_system"] == source_system.value
        return ClaimResult(
            granted=bool(created or same_source),
            claim_id=int(row["id"]),
            denial_reason=(
                None if created or same_source else "episode_already_claimed"
            ),
        )

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        return sqlite_insert(table)


class NativePlanRepository:
    """Persist plans only; this class has no provider or browser mutation path."""

    AUTOMATION_STATUSES = {
        "draft",
        "ready_to_configure",
        "operator_confirmed_on_fansly",
        "verified_by_observed_send",
        "needs_reverification",
        "disabled",
    }

    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def fingerprint(message_text: str, media: object = None) -> str:
        canonical = json.dumps(
            {"message_text": message_text, "media": media},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def create_automation(
        self,
        *,
        creator_id: str,
        name: str,
        trigger_type: TriggerType,
        message_text: str,
        delay_seconds: int = 0,
        cooldown_seconds: int = 0,
    ) -> int:
        if trigger_type in {
            TriggerType.ONLINE,
            TriggerType.STALLED,
            TriggerType.INBOUND_REPLY,
        }:
            raise ValueError("trigger is not a documented native automation")
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(NATIVE_AUTOMATIONS).values(
                    creator_id=creator_id,
                    name=name[:128],
                    trigger_type=trigger_type.value,
                    intended_enabled=False,
                    audience={},
                    tier_filters=[],
                    tip_keyword=None,
                    tip_threshold=None,
                    delay_seconds=max(0, delay_seconds),
                    cooldown_seconds=max(0, cooldown_seconds),
                    message_text=message_text,
                    message_hash=self.fingerprint(message_text),
                    media_reference=None,
                    locked_text=False,
                    configuration_status="draft",
                    provider_automation_id=None,
                    operator_verified_at=None,
                    last_observed_send_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return int(result.inserted_primary_key[0])

    def create_campaign(
        self,
        *,
        creator_id: str,
        name: str,
        message_text: str,
        audience: dict | None = None,
        cooldown_seconds: int = 0,
    ) -> int:
        """Store a conversation-only campaign draft without sending it."""
        normalized_name = str(name or "").strip()
        normalized_message = str(message_text or "").strip()
        if not normalized_name:
            raise ValueError("campaign name is required")
        if not normalized_message:
            raise ValueError("campaign message is required")
        if len(normalized_message) > 2000:
            raise ValueError("campaign message must be 2,000 characters or fewer")
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(NATIVE_CAMPAIGNS).values(
                    creator_id=creator_id,
                    name=normalized_name[:128],
                    audience=audience or {"segment": "all"},
                    included_tiers=[],
                    included_lists=[],
                    excluded_lists=[],
                    exclude_offline=False,
                    exclude_creators=True,
                    scheduled_time=None,
                    cooldown_seconds=max(0, int(cooldown_seconds)),
                    message_text=normalized_message,
                    content_fingerprint=self.fingerprint(
                        normalized_message,
                    ),
                    media_metadata={},
                    conversation_only=True,
                    ppv_blocked=True,
                    operator_status="draft",
                    sent_at=None,
                    observed_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return int(result.inserted_primary_key[0])

    def list_campaigns(
        self,
        creator_id: str,
        *,
        limit: int = 100,
    ) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(NATIVE_CAMPAIGNS)
                .where(NATIVE_CAMPAIGNS.c.creator_id == creator_id)
                .order_by(desc(NATIVE_CAMPAIGNS.c.created_at))
                .limit(min(max(int(limit), 1), 100))
            ).mappings().all()
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "message_text": row["message_text"],
                "audience": row["audience"] or {},
                "cooldown_seconds": int(row["cooldown_seconds"] or 0),
                "status": row["operator_status"],
                "conversation_only": bool(row["conversation_only"]),
                "ppv_blocked": bool(row["ppv_blocked"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
