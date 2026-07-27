"""Tenant-scoped repositories for durable Brain 2.0 state."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from sqlalchemy import and_, desc, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.conversation.brain2_schema import (
    BRAIN_EXPERIMENT_ASSIGNMENTS,
    BRAIN_EXPERIMENTS,
    CONVERSATION_OUTCOMES,
    FAN_CONVERSATION_STATES,
    FAN_MEMORIES_V2,
)
from src.persistence.schema import utcnow


class _Repository:
    def __init__(self, engine):
        self.engine = engine

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(f"Unsupported database dialect: {self.engine.dialect.name}")


class ConversationOutcomeRepository(_Repository):
    def create_for_delivery(self, **values) -> int:
        now = utcnow()
        if "decision_id" in values:
            values["conversation_decision_id"] = values.pop("decision_id")
        payload = {
            **values,
            "fan_replied": False,
            "continued_three_turns": False,
            "returned_within_24h": False,
            "stalled_recovered": False,
            "negative_signal": False,
            "additional_turns": 0,
            "created_at": now,
            "updated_at": now,
        }
        statement = self._insert(CONVERSATION_OUTCOMES).values(**payload)
        statement = statement.on_conflict_do_nothing(
            index_elements=["outbox_message_id"]
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
            outcome_id = connection.execute(
                select(CONVERSATION_OUTCOMES.c.id).where(
                    CONVERSATION_OUTCOMES.c.outbox_message_id
                    == values["outbox_message_id"]
                )
            ).scalar_one()
        return int(outcome_id)

    def attribute_inbound_reply(
        self,
        *,
        creator_id: str,
        fan_id: str,
        inbound_message_id: int,
        received_at: datetime,
        meaningful: bool,
    ) -> int | None:
        received_at = _aware(received_at)
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(CONVERSATION_OUTCOMES.c.id).where(
                    CONVERSATION_OUTCOMES.c.reply_inbound_message_id
                    == inbound_message_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing)
            row = connection.execute(
                select(CONVERSATION_OUTCOMES)
                .where(
                    and_(
                        CONVERSATION_OUTCOMES.c.creator_id == creator_id,
                        CONVERSATION_OUTCOMES.c.fan_id == fan_id,
                        CONVERSATION_OUTCOMES.c.sent_at <= received_at,
                        CONVERSATION_OUTCOMES.c.attribution_closed_at.is_(None),
                        CONVERSATION_OUTCOMES.c.reply_inbound_message_id.is_(None),
                    )
                )
                .order_by(desc(CONVERSATION_OUTCOMES.c.sent_at))
                .limit(1)
            ).mappings().first()
            if row is None:
                return None
            sent_at = _aware(row["sent_at"])
            latency = max(0, int((received_at - sent_at).total_seconds()))
            connection.execute(
                update(CONVERSATION_OUTCOMES)
                .where(CONVERSATION_OUTCOMES.c.id == row["id"])
                .values(
                    fan_replied=True,
                    reply_inbound_message_id=inbound_message_id,
                    reply_latency_seconds=latency,
                    meaningful_reply=bool(meaningful),
                    stalled_recovered=row["trigger_kind"] == "stalled",
                    updated_at=utcnow(),
                )
            )
            return int(row["id"])

    def get(self, outcome_id: int) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(CONVERSATION_OUTCOMES).where(
                    CONVERSATION_OUTCOMES.c.id == outcome_id
                )
            ).mappings().first()
        return dict(row) if row else None


class FanMemoryV2Repository(_Repository):
    def remember(
        self,
        *,
        creator_id: str,
        fan_id: str,
        memory_type: str,
        normalized_value: str,
        display_value: str,
        confidence: float,
        importance: float,
        source_message_id: str,
        source_timestamp: datetime,
        contradiction_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> int:
        now = utcnow()
        memory_key = contradiction_key or (
            normalized_value.split("=", 1)[0].strip()
            if "=" in normalized_value
            else None
        )
        values = {
            "creator_id": creator_id,
            "fan_id": fan_id,
            "memory_type": memory_type,
            "memory_key": memory_key,
            "normalized_value": normalized_value.strip(),
            "display_value": display_value.strip(),
            "confidence": min(max(float(confidence), 0.0), 1.0),
            "importance": min(max(float(importance), 0.0), 1.0),
            "source_message_id": source_message_id,
            "source_timestamp": source_timestamp,
            "first_seen_at": now,
            "last_confirmed_at": now,
            "expires_at": expires_at,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        statement = self._insert(FAN_MEMORIES_V2).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                "creator_id",
                "fan_id",
                "memory_type",
                "normalized_value",
            ],
            set_={
                "display_value": values["display_value"],
                "confidence": values["confidence"],
                "importance": values["importance"],
                "last_confirmed_at": now,
                "updated_at": now,
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
            memory_id = connection.execute(
                select(FAN_MEMORIES_V2.c.id).where(
                    and_(
                        FAN_MEMORIES_V2.c.creator_id == creator_id,
                        FAN_MEMORIES_V2.c.fan_id == fan_id,
                        FAN_MEMORIES_V2.c.memory_type == memory_type,
                        FAN_MEMORIES_V2.c.normalized_value
                        == values["normalized_value"],
                    )
                )
            ).scalar_one()
            if memory_key:
                connection.execute(
                    update(FAN_MEMORIES_V2)
                    .where(
                        and_(
                            FAN_MEMORIES_V2.c.creator_id == creator_id,
                            FAN_MEMORIES_V2.c.fan_id == fan_id,
                            FAN_MEMORIES_V2.c.memory_type == memory_type,
                            FAN_MEMORIES_V2.c.memory_key == memory_key,
                            FAN_MEMORIES_V2.c.id != memory_id,
                            FAN_MEMORIES_V2.c.status == "active",
                        )
                    )
                    .values(
                        status="superseded",
                        superseded_by_id=memory_id,
                        updated_at=now,
                    )
                )
        return int(memory_id)

    def relevant(self, *, creator_id: str, fan_id: str, limit: int = 20) -> list[dict]:
        now = utcnow()
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(FAN_MEMORIES_V2)
                .where(
                    and_(
                        FAN_MEMORIES_V2.c.creator_id == creator_id,
                        FAN_MEMORIES_V2.c.fan_id == fan_id,
                        FAN_MEMORIES_V2.c.status == "active",
                        or_(
                            FAN_MEMORIES_V2.c.expires_at.is_(None),
                            FAN_MEMORIES_V2.c.expires_at > now,
                        ),
                    )
                )
                .order_by(
                    desc(FAN_MEMORIES_V2.c.importance),
                    desc(FAN_MEMORIES_V2.c.confidence),
                    desc(FAN_MEMORIES_V2.c.last_confirmed_at),
                )
                .limit(max(1, min(int(limit), 100)))
            ).mappings().all()
        return [dict(row) for row in rows]

    def get(self, memory_id: int) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(FAN_MEMORIES_V2).where(FAN_MEMORIES_V2.c.id == memory_id)
            ).mappings().first()
        return dict(row) if row else None


class FanConversationStateRepository(_Repository):
    def get_or_create(self, creator_id: str, fan_id: str) -> dict:
        now = utcnow()
        values = {
            "creator_id": creator_id,
            "fan_id": fan_id,
            "relationship_stage": "unknown",
            "current_mood": "unknown",
            "current_energy": "unknown",
            "engagement_estimate": 0.5,
            "recent_objectives": [],
            "recent_tactics": [],
            "question_streak": 0,
            "pet_name_streak": 0,
            "state_version": 1,
            "created_at": now,
            "updated_at": now,
        }
        statement = self._insert(FAN_CONVERSATION_STATES).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=["creator_id", "fan_id"]
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
            row = connection.execute(
                select(FAN_CONVERSATION_STATES).where(
                    and_(
                        FAN_CONVERSATION_STATES.c.creator_id == creator_id,
                        FAN_CONVERSATION_STATES.c.fan_id == fan_id,
                    )
                )
            ).mappings().one()
        return dict(row)

    def update(
        self,
        *,
        creator_id: str,
        fan_id: str,
        expected_version: int,
        changes: dict,
    ) -> dict | None:
        allowed = {
            column.name
            for column in FAN_CONVERSATION_STATES.columns
            if column.name
            not in {"creator_id", "fan_id", "created_at", "state_version"}
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        values.update(state_version=expected_version + 1, updated_at=utcnow())
        with self.engine.begin() as connection:
            result = connection.execute(
                update(FAN_CONVERSATION_STATES)
                .where(
                    and_(
                        FAN_CONVERSATION_STATES.c.creator_id == creator_id,
                        FAN_CONVERSATION_STATES.c.fan_id == fan_id,
                        FAN_CONVERSATION_STATES.c.state_version == expected_version,
                    )
                )
                .values(**values)
            )
            if result.rowcount != 1:
                return None
            row = connection.execute(
                select(FAN_CONVERSATION_STATES).where(
                    and_(
                        FAN_CONVERSATION_STATES.c.creator_id == creator_id,
                        FAN_CONVERSATION_STATES.c.fan_id == fan_id,
                    )
                )
            ).mappings().one()
        return dict(row)


class PersistentExperimentRepository(_Repository):
    def create(
        self,
        *,
        creator_id: str,
        name: str,
        variants: dict[str, int],
        minimum_sample_size: int,
    ) -> int:
        if not variants or any(int(weight) <= 0 for weight in variants.values()):
            raise ValueError("variants require positive weights")
        now = utcnow()
        with self.engine.begin() as connection:
            result = connection.execute(
                self._insert(BRAIN_EXPERIMENTS).values(
                    creator_id=creator_id,
                    name=name,
                    status="active",
                    variants=variants,
                    minimum_sample_size=max(2, int(minimum_sample_size)),
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            return int(result.inserted_primary_key[0])

    def assign(
        self,
        *,
        experiment_id: int,
        creator_id: str,
        fan_id: str,
    ) -> str | None:
        with self.engine.begin() as connection:
            experiment = connection.execute(
                select(BRAIN_EXPERIMENTS).where(
                    and_(
                        BRAIN_EXPERIMENTS.c.id == experiment_id,
                        BRAIN_EXPERIMENTS.c.creator_id == creator_id,
                    )
                )
            ).mappings().first()
            if experiment is None or experiment["status"] != "active":
                return None
            existing = connection.execute(
                select(BRAIN_EXPERIMENT_ASSIGNMENTS.c.variant).where(
                    and_(
                        BRAIN_EXPERIMENT_ASSIGNMENTS.c.experiment_id
                        == experiment_id,
                        BRAIN_EXPERIMENT_ASSIGNMENTS.c.creator_id == creator_id,
                        BRAIN_EXPERIMENT_ASSIGNMENTS.c.fan_id == fan_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            variants = experiment["variants"]
            total = sum(int(weight) for weight in variants.values())
            point = int.from_bytes(
                hashlib.sha256(
                    f"{experiment_id}:{creator_id}:{fan_id}".encode()
                ).digest()[:8],
                "big",
            ) % total
            running = 0
            variant = next(iter(variants))
            for key, weight in variants.items():
                running += int(weight)
                if point < running:
                    variant = key
                    break
            statement = self._insert(BRAIN_EXPERIMENT_ASSIGNMENTS).values(
                experiment_id=experiment_id,
                creator_id=creator_id,
                fan_id=fan_id,
                variant=variant,
                assigned_at=utcnow(),
            )
            statement = statement.on_conflict_do_nothing(
                index_elements=["experiment_id", "creator_id", "fan_id"]
            )
            connection.execute(statement)
            return str(
                connection.execute(
                    select(BRAIN_EXPERIMENT_ASSIGNMENTS.c.variant).where(
                        and_(
                            BRAIN_EXPERIMENT_ASSIGNMENTS.c.experiment_id
                            == experiment_id,
                            BRAIN_EXPERIMENT_ASSIGNMENTS.c.creator_id == creator_id,
                            BRAIN_EXPERIMENT_ASSIGNMENTS.c.fan_id == fan_id,
                        )
                    )
                ).scalar_one()
            )

    def pause(self, experiment_id: int, *, creator_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(BRAIN_EXPERIMENTS)
                .where(
                    and_(
                        BRAIN_EXPERIMENTS.c.id == experiment_id,
                        BRAIN_EXPERIMENTS.c.creator_id == creator_id,
                    )
                )
                .values(status="paused", updated_at=utcnow())
            )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
