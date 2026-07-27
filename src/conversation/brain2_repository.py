"""Tenant-scoped repositories for durable Brain 2.0 state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.conversation.brain2_schema import (
    BRAIN_EXPERIMENT_ASSIGNMENTS,
    BRAIN_EXPERIMENT_EVENTS,
    BRAIN_EXPERIMENTS,
    BRAIN_SHADOW_RUNS,
    BRAIN_USAGE_BUCKETS,
    CONVERSATION_EPISODES,
    CONVERSATION_OUTCOMES,
    FAN_CONVERSATION_STATES,
    FAN_MEMORIES_V2,
)
from src.persistence.schema import INBOUND_MESSAGES, utcnow


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
        negative_signal: bool = False,
    ) -> int | None:
        """Attribute one durable inbound event to the newest eligible outcome.

        The first reply claims the newest unclaimed creator turn. Later inbound
        events update that same newest open outcome from durable inbound rows,
        so duplicate webhook/reconciliation delivery cannot inflate counters.
        """
        received_at = _aware(received_at)
        now = utcnow()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(CONVERSATION_OUTCOMES).where(
                    CONVERSATION_OUTCOMES.c.reply_inbound_message_id
                    == inbound_message_id
                )
            ).mappings().first()
            if existing is not None:
                return int(existing["id"])
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
            first_reply = row is not None
            if row is None:
                row = connection.execute(
                    select(CONVERSATION_OUTCOMES)
                    .where(
                        and_(
                            CONVERSATION_OUTCOMES.c.creator_id == creator_id,
                            CONVERSATION_OUTCOMES.c.fan_id == fan_id,
                            CONVERSATION_OUTCOMES.c.sent_at <= received_at,
                            CONVERSATION_OUTCOMES.c.attribution_closed_at.is_(None),
                            CONVERSATION_OUTCOMES.c.reply_inbound_message_id.is_not(None),
                        )
                    )
                    .order_by(desc(CONVERSATION_OUTCOMES.c.sent_at))
                    .limit(1)
                ).mappings().first()
            if row is None:
                return None
            sent_at = _aware(row["sent_at"])
            latency = max(0, int((received_at - sent_at).total_seconds()))
            durable_turns = int(
                connection.execute(
                    select(func.count())
                    .select_from(INBOUND_MESSAGES)
                    .where(
                        and_(
                            INBOUND_MESSAGES.c.creator_id == creator_id,
                            INBOUND_MESSAGES.c.fan_id == fan_id,
                            INBOUND_MESSAGES.c.provider_created_at > sent_at,
                            INBOUND_MESSAGES.c.provider_created_at <= received_at,
                        )
                    )
                ).scalar_one()
                or 0
            )
            additional_turns = max(
                durable_turns,
                1 if first_reply else int(row["additional_turns"] or 0),
            )
            values = {
                "fan_replied": True,
                "additional_turns": additional_turns,
                "continued_three_turns": additional_turns >= 3,
                "negative_signal": bool(row["negative_signal"]) or bool(negative_signal),
                "updated_at": now,
            }
            if first_reply:
                values.update(
                    reply_inbound_message_id=inbound_message_id,
                    reply_latency_seconds=latency,
                    meaningful_reply=bool(meaningful),
                    returned_within_24h=latency <= 86_400,
                    stalled_recovered=row["trigger_kind"] == "stalled",
                )
            connection.execute(
                update(CONVERSATION_OUTCOMES)
                .where(CONVERSATION_OUTCOMES.c.id == row["id"])
                .values(**values)
            )
            return int(row["id"])

    def close_expired(
        self,
        *,
        creator_id: str,
        now: datetime | None = None,
        window_hours: int = 24,
    ) -> int:
        now = _aware(now or utcnow())
        cutoff = now - timedelta(hours=max(1, min(int(window_hours), 168)))
        with self.engine.begin() as connection:
            result = connection.execute(
                update(CONVERSATION_OUTCOMES)
                .where(
                    and_(
                        CONVERSATION_OUTCOMES.c.creator_id == creator_id,
                        CONVERSATION_OUTCOMES.c.attribution_closed_at.is_(None),
                        CONVERSATION_OUTCOMES.c.sent_at <= cutoff,
                    )
                )
                .values(attribution_closed_at=now, updated_at=now)
            )
        return int(result.rowcount or 0)

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
            experiment_id = int(result.inserted_primary_key[0])
            connection.execute(
                self._insert(BRAIN_EXPERIMENT_EVENTS).values(
                    experiment_id=experiment_id,
                    creator_id=creator_id,
                    event_type="created",
                    actor="crm",
                    details={
                        "variants": variants,
                        "minimum_sample_size": max(
                            2,
                            int(minimum_sample_size),
                        ),
                    },
                    created_at=now,
                )
            )
            return experiment_id

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
        now = utcnow()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(BRAIN_EXPERIMENTS)
                .where(
                    and_(
                        BRAIN_EXPERIMENTS.c.id == experiment_id,
                        BRAIN_EXPERIMENTS.c.creator_id == creator_id,
                        BRAIN_EXPERIMENTS.c.status == "active",
                    )
                )
                .values(
                    status="paused",
                    ended_at=now,
                    updated_at=now,
                )
            )
            if result.rowcount:
                connection.execute(
                    self._insert(BRAIN_EXPERIMENT_EVENTS).values(
                        experiment_id=experiment_id,
                        creator_id=creator_id,
                        event_type="paused",
                        actor="crm",
                        details={},
                        created_at=now,
                    )
                )

    def events(
        self,
        *,
        experiment_id: int,
        creator_id: str,
    ) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(BRAIN_EXPERIMENT_EVENTS)
                .where(
                    and_(
                        BRAIN_EXPERIMENT_EVENTS.c.experiment_id == experiment_id,
                        BRAIN_EXPERIMENT_EVENTS.c.creator_id == creator_id,
                    )
                )
                .order_by(BRAIN_EXPERIMENT_EVENTS.c.created_at)
            ).mappings().all()
        return [dict(row) for row in rows]

    def list_for_creator(self, creator_id: str) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(BRAIN_EXPERIMENTS)
                .where(BRAIN_EXPERIMENTS.c.creator_id == creator_id)
                .order_by(desc(BRAIN_EXPERIMENTS.c.created_at))
            ).mappings().all()
        return [dict(row) for row in rows]


class StrategicUsageCapRepository(_Repository):
    def reserve(
        self,
        *,
        creator_id: str,
        calls: int,
        hourly_limit: int,
        daily_limit: int,
        now: datetime | None = None,
    ) -> bool:
        calls = max(1, int(calls))
        if hourly_limit < calls or daily_limit < calls:
            return False
        current = _aware(now or utcnow())
        hour = current.replace(minute=0, second=0, microsecond=0)
        day = current.replace(hour=0, minute=0, second=0, microsecond=0)
        buckets = (
            ("hour", hour, int(hourly_limit)),
            ("day", day, int(daily_limit)),
        )
        with self.engine.begin() as connection:
            for kind, start, limit in buckets:
                statement = self._insert(BRAIN_USAGE_BUCKETS).values(
                    creator_id=creator_id,
                    bucket_kind=kind,
                    bucket_start=start,
                    used_calls=0,
                    limit_snapshot=limit,
                    updated_at=utcnow(),
                )
                statement = statement.on_conflict_do_nothing(
                    index_elements=[
                        "creator_id",
                        "bucket_kind",
                        "bucket_start",
                    ]
                )
                connection.execute(statement)
            rows = connection.execute(
                select(BRAIN_USAGE_BUCKETS)
                .where(
                    and_(
                        BRAIN_USAGE_BUCKETS.c.creator_id == creator_id,
                        or_(
                            and_(
                                BRAIN_USAGE_BUCKETS.c.bucket_kind == "hour",
                                BRAIN_USAGE_BUCKETS.c.bucket_start == hour,
                            ),
                            and_(
                                BRAIN_USAGE_BUCKETS.c.bucket_kind == "day",
                                BRAIN_USAGE_BUCKETS.c.bucket_start == day,
                            ),
                        ),
                    )
                )
                .with_for_update()
            ).mappings().all()
            if len(rows) != 2 or any(
                int(row["used_calls"]) + calls
                > (
                    hourly_limit
                    if row["bucket_kind"] == "hour"
                    else daily_limit
                )
                for row in rows
            ):
                return False
            for row in rows:
                connection.execute(
                    update(BRAIN_USAGE_BUCKETS)
                    .where(
                        and_(
                            BRAIN_USAGE_BUCKETS.c.creator_id == creator_id,
                            BRAIN_USAGE_BUCKETS.c.bucket_kind
                            == row["bucket_kind"],
                            BRAIN_USAGE_BUCKETS.c.bucket_start
                            == row["bucket_start"],
                        )
                    )
                    .values(
                        used_calls=int(row["used_calls"]) + calls,
                        limit_snapshot=(
                            hourly_limit
                            if row["bucket_kind"] == "hour"
                            else daily_limit
                        ),
                        updated_at=utcnow(),
                    )
                )
        return True

class ConversationEpisodeRepository(_Repository):
    def save(self, **values) -> int:
        now = utcnow()
        payload = {
            **values,
            "created_at": now,
            "updated_at": now,
        }
        statement = self._insert(CONVERSATION_EPISODES).values(**payload)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=["creator_id", "fan_id", "episode_key"],
            set_={
                "main_topics": excluded.main_topics,
                "emotional_tone": excluded.emotional_tone,
                "fan_disclosures": excluded.fan_disclosures,
                "creator_statements": excluded.creator_statements,
                "boundaries": excluded.boundaries,
                "resolved_threads": excluded.resolved_threads,
                "unresolved_threads": excluded.unresolved_threads,
                "future_callback": excluded.future_callback,
                "source_start_message_id": excluded.source_start_message_id,
                "source_end_message_id": excluded.source_end_message_id,
                "episode_started_at": excluded.episode_started_at,
                "episode_ended_at": excluded.episode_ended_at,
                "updated_at": now,
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
            episode_id = connection.execute(
                select(CONVERSATION_EPISODES.c.id).where(
                    and_(
                        CONVERSATION_EPISODES.c.creator_id
                        == values["creator_id"],
                        CONVERSATION_EPISODES.c.fan_id == values["fan_id"],
                        CONVERSATION_EPISODES.c.episode_key
                        == values["episode_key"],
                    )
                )
            ).scalar_one()
        return int(episode_id)

    def get(self, episode_id: int) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(CONVERSATION_EPISODES).where(
                    CONVERSATION_EPISODES.c.id == episode_id
                )
            ).mappings().first()
        return dict(row) if row else None

    def recent(
        self,
        *,
        creator_id: str,
        fan_id: str,
        limit: int = 5,
    ) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(CONVERSATION_EPISODES)
                .where(
                    and_(
                        CONVERSATION_EPISODES.c.creator_id == creator_id,
                        CONVERSATION_EPISODES.c.fan_id == fan_id,
                    )
                )
                .order_by(desc(CONVERSATION_EPISODES.c.episode_ended_at))
                .limit(max(1, min(int(limit), 20)))
            ).mappings().all()
        return [dict(row) for row in rows]

class ShadowRunRepository(_Repository):
    """Persist shadow-only analysis with no outbox dependency."""

    def enqueue(
        self,
        *,
        inbound_message_id: int,
        creator_id: str,
        fan_id: str,
        brain_version: str,
        route: str,
        router: dict,
    ) -> tuple[int, bool]:
        values = {
            "inbound_message_id": inbound_message_id,
            "creator_id": creator_id,
            "fan_id": fan_id,
            "brain_version": brain_version,
            "status": "queued",
            "route": route,
            "router": router,
            "gate": {},
            "model_calls": 0,
            "latency_ms": 0,
            "created_at": utcnow(),
        }
        statement = self._insert(BRAIN_SHADOW_RUNS).values(**values)
        statement = statement.on_conflict_do_nothing(
            index_elements=["inbound_message_id", "brain_version"]
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            created = result.rowcount == 1
            run_id = connection.execute(
                select(BRAIN_SHADOW_RUNS.c.id).where(
                    and_(
                        BRAIN_SHADOW_RUNS.c.inbound_message_id
                        == inbound_message_id,
                        BRAIN_SHADOW_RUNS.c.brain_version == brain_version,
                    )
                )
            ).scalar_one()
        return int(run_id), created

    def complete(
        self,
        run_id: int,
        *,
        planner: dict,
        candidates: list[dict],
        judge: dict,
        gate: dict,
        selected_candidate: str | None,
        model_calls: int,
        latency_ms: int,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(BRAIN_SHADOW_RUNS)
                .where(BRAIN_SHADOW_RUNS.c.id == run_id)
                .values(
                    status="completed",
                    planner=planner,
                    candidates=candidates,
                    judge=judge,
                    gate=gate,
                    selected_candidate=selected_candidate,
                    model_calls=model_calls,
                    latency_ms=latency_ms,
                    completed_at=utcnow(),
                )
            )

    def mark_capped(self, run_id: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(BRAIN_SHADOW_RUNS)
                .where(BRAIN_SHADOW_RUNS.c.id == run_id)
                .values(
                    status="capped",
                    error_code="strategic_call_cap",
                    completed_at=utcnow(),
                )
            )

    def fail(self, run_id: int, *, error_code: str, latency_ms: int) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(BRAIN_SHADOW_RUNS)
                .where(BRAIN_SHADOW_RUNS.c.id == run_id)
                .values(
                    status="failed",
                    error_code=str(error_code)[:128],
                    latency_ms=latency_ms,
                    completed_at=utcnow(),
                )
            )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
