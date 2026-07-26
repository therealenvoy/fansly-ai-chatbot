"""Repositories for persistent conversation and processing state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import Engine, and_, case, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from src.funnel.session import FanSession
from src.funnel.spiral import EscalationLevel, SpiralPhase
from src.rhythm.engine import PushPullEngine, RhythmPhase

from .schema import (
    CONVERSATIONS,
    CREATORS,
    FANS,
    FAN_RUNTIME_STATES,
    POLL_CURSORS,
    PROCESSED_PLATFORM_MESSAGES,
    utcnow,
)


@dataclass
class DurableFanState:
    creator_id: str
    fan_id: str
    phase: str = "rapport"
    phase_history: list[str] = field(default_factory=lambda: ["rapport"])
    messages_in_phase: int = 0
    escalation_level: int = 0
    ppvs_bought: int = 0
    cooldown: bool = False
    consecutive_rejections: int = 0
    warmup: bool = False
    last_activity_at: Optional[datetime] = None
    message_count: int = 0
    extract_counter: int = 0
    purchase_count_seen: int = 0
    rhythm_phase_history: list[str] = field(default_factory=lambda: ["pull"])
    rhythm_push_count: int = 0
    rhythm_pull_count: int = 0
    version: int = 0


class ConcurrentStateUpdate(RuntimeError):
    """Raised when another worker saved the same fan state first."""


class ConversationStateRepository:
    """PostgreSQL-first repository for state that previously lived in dicts."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def ensure_creator(self, creator_id: str) -> None:
        now = utcnow()
        stmt = self._insert(CREATORS).values(
            id=creator_id,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={"updated_at": now},
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def ensure_conversation(
        self,
        creator_id: str,
        fan_id: str,
        chat_id: str,
        *,
        display_name: str | None = None,
        username: str | None = None,
        avatar_url: str | None = None,
    ) -> None:
        self.ensure_creator(creator_id)
        now = utcnow()
        fan_stmt = self._insert(FANS).values(
            creator_id=creator_id,
            fan_id=fan_id,
            display_name=display_name,
            username=username,
            avatar_url=avatar_url,
            created_at=now,
            updated_at=now,
        )
        fan_updates = {"updated_at": now}
        if display_name:
            fan_updates["display_name"] = display_name
        if username:
            fan_updates["username"] = username
        if avatar_url:
            fan_updates["avatar_url"] = avatar_url
        fan_stmt = fan_stmt.on_conflict_do_update(
            index_elements=["creator_id", "fan_id"],
            set_=fan_updates,
        )
        conversation_stmt = self._insert(CONVERSATIONS).values(
            creator_id=creator_id,
            chat_id=chat_id,
            fan_id=fan_id,
            created_at=now,
            updated_at=now,
        )
        conversation_stmt = conversation_stmt.on_conflict_do_update(
            index_elements=["creator_id", "chat_id"],
            set_={
                "fan_id": fan_id,
                "updated_at": now,
            },
        )
        with self.engine.begin() as conn:
            conn.execute(fan_stmt)
            conn.execute(conversation_stmt)

    def get_conversation_checkpoint(
        self,
        creator_id: str,
        chat_id: str,
    ) -> tuple[str | None, str | None]:
        """Return ``(last_platform_message_id, provider_cursor)`` for a chat."""
        stmt = select(
            CONVERSATIONS.c.last_platform_message_id,
            CONVERSATIONS.c.provider_cursor,
        ).where(
            and_(
                CONVERSATIONS.c.creator_id == creator_id,
                CONVERSATIONS.c.chat_id == chat_id,
            )
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        if row is None:
            return None, None
        return row[0], row[1]

    def conversation_changed(
        self,
        creator_id: str,
        chat_id: str,
        last_platform_message_id: str | None,
    ) -> bool:
        """Whether the provider's chat head differs from our durable head."""
        stored, _ = self.get_conversation_checkpoint(creator_id, chat_id)
        return stored != last_platform_message_id

    def update_conversation_checkpoint(
        self,
        creator_id: str,
        chat_id: str,
        *,
        last_platform_message_id: str | None,
        provider_cursor: str | None = None,
        last_activity_at: datetime | None = None,
    ) -> None:
        """Advance a chat checkpoint only after its messages were ingested."""
        values = {
            "last_platform_message_id": last_platform_message_id,
            "provider_cursor": provider_cursor,
            "updated_at": utcnow(),
        }
        if last_activity_at is not None:
            values["last_activity_at"] = last_activity_at
        with self.engine.begin() as conn:
            result = conn.execute(
                update(CONVERSATIONS)
                .where(
                    and_(
                        CONVERSATIONS.c.creator_id == creator_id,
                        CONVERSATIONS.c.chat_id == chat_id,
                    )
                )
                .values(**values)
            )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Conversation does not exist: {creator_id}/{chat_id}"
            )

    def record_crm_activity(
        self,
        creator_id: str,
        chat_id: str,
        *,
        last_activity_at: datetime,
    ) -> None:
        """Advance CRM activity time without touching reply checkpoints."""
        current = CONVERSATIONS.c.last_activity_at
        with self.engine.begin() as conn:
            result = conn.execute(
                update(CONVERSATIONS)
                .where(
                    and_(
                        CONVERSATIONS.c.creator_id == creator_id,
                        CONVERSATIONS.c.chat_id == chat_id,
                    )
                )
                .values(
                    last_activity_at=case(
                        (current.is_(None), last_activity_at),
                        (current < last_activity_at, last_activity_at),
                        else_=current,
                    ),
                    updated_at=utcnow(),
                )
            )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Conversation does not exist: {creator_id}/{chat_id}"
            )

    def load_state(self, creator_id: str, fan_id: str) -> DurableFanState | None:
        stmt = select(FAN_RUNTIME_STATES).where(
            and_(
                FAN_RUNTIME_STATES.c.creator_id == creator_id,
                FAN_RUNTIME_STATES.c.fan_id == fan_id,
            )
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        if row is None:
            return None
        return DurableFanState(
            creator_id=row["creator_id"],
            fan_id=row["fan_id"],
            phase=row["phase"],
            phase_history=list(row["phase_history"] or ["rapport"]),
            messages_in_phase=row["messages_in_phase"],
            escalation_level=row["escalation_level"],
            ppvs_bought=row["ppvs_bought"],
            cooldown=bool(row["cooldown"]),
            consecutive_rejections=row["consecutive_rejections"],
            warmup=bool(row["warmup"]),
            last_activity_at=row["last_activity_at"],
            message_count=row["message_count"],
            extract_counter=row["extract_counter"],
            purchase_count_seen=row["purchase_count_seen"],
            rhythm_phase_history=list(row["rhythm_phase_history"] or ["pull"]),
            rhythm_push_count=row["rhythm_push_count"],
            rhythm_pull_count=row["rhythm_pull_count"],
            version=row["version"],
        )

    def save_state(self, state: DurableFanState) -> DurableFanState:
        self.ensure_creator(state.creator_id)
        now = utcnow()
        next_version = state.version + 1
        values = {
            "creator_id": state.creator_id,
            "fan_id": state.fan_id,
            "phase": state.phase,
            "phase_history": state.phase_history,
            "messages_in_phase": state.messages_in_phase,
            "escalation_level": state.escalation_level,
            "ppvs_bought": state.ppvs_bought,
            "cooldown": state.cooldown,
            "consecutive_rejections": state.consecutive_rejections,
            "warmup": state.warmup,
            "last_activity_at": state.last_activity_at,
            "message_count": state.message_count,
            "extract_counter": state.extract_counter,
            "purchase_count_seen": state.purchase_count_seen,
            "rhythm_phase_history": state.rhythm_phase_history,
            "rhythm_push_count": state.rhythm_push_count,
            "rhythm_pull_count": state.rhythm_pull_count,
            "version": next_version,
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as conn:
            if state.version == 0:
                try:
                    conn.execute(FAN_RUNTIME_STATES.insert().values(**values))
                except IntegrityError as exc:
                    raise ConcurrentStateUpdate(
                        f"Concurrent initial state write for {state.creator_id}/{state.fan_id}"
                    ) from exc
            else:
                result = conn.execute(
                    update(FAN_RUNTIME_STATES)
                    .where(
                        and_(
                            FAN_RUNTIME_STATES.c.creator_id
                            == state.creator_id,
                            FAN_RUNTIME_STATES.c.fan_id == state.fan_id,
                            FAN_RUNTIME_STATES.c.version == state.version,
                        )
                    )
                    .values(
                        **{
                            key: value
                            for key, value in values.items()
                            if key
                            not in {
                                "creator_id",
                                "fan_id",
                                "created_at",
                            }
                        }
                    )
                )
                if result.rowcount != 1:
                    raise ConcurrentStateUpdate(
                        f"Stale state version for {state.creator_id}/{state.fan_id}"
                    )
        state.version = next_version
        return state

    def load_session(self, creator_id: str, fan_id: str) -> tuple[FanSession, DurableFanState]:
        state = self.load_state(creator_id, fan_id)
        if state is None:
            state = DurableFanState(creator_id=creator_id, fan_id=fan_id)
        session = FanSession(fan_id=fan_id, creator_id=creator_id)
        session.funnel._phase = SpiralPhase(state.phase)
        session.funnel.phase_history = [
            SpiralPhase(value) for value in state.phase_history
        ]
        session.funnel.messages_in_phase = state.messages_in_phase
        session.funnel.level = EscalationLevel(
            number=state.escalation_level,
            ppvs_bought=state.ppvs_bought,
        )
        session.funnel.cooldown = state.cooldown
        session.funnel.consecutive_rejections = state.consecutive_rejections
        session.funnel._warmup = state.warmup
        session.last_activity = state.last_activity_at
        session.persisted_message_count = state.message_count
        return session, state

    def capture_session(
        self,
        session: FanSession,
        *,
        extract_counter: int = 0,
        purchase_count_seen: int = 0,
        rhythm: PushPullEngine | None = None,
        version: int = 0,
    ) -> DurableFanState:
        rhythm = rhythm or PushPullEngine()
        return DurableFanState(
            creator_id=session.creator_id,
            fan_id=session.fan_id,
            phase=session.funnel.current_stage.value,
            phase_history=[phase.value for phase in session.funnel.phase_history],
            messages_in_phase=session.funnel.messages_in_phase,
            escalation_level=session.funnel.level.number,
            ppvs_bought=session.funnel.level.ppvs_bought,
            cooldown=session.funnel.cooldown,
            consecutive_rejections=session.funnel.consecutive_rejections,
            warmup=session.funnel.is_warmup,
            last_activity_at=session.last_activity,
            message_count=session.message_count,
            extract_counter=extract_counter,
            purchase_count_seen=purchase_count_seen,
            rhythm_phase_history=[phase.value for phase in rhythm.phase_history],
            rhythm_push_count=rhythm.push_count,
            rhythm_pull_count=rhythm.pull_count,
            version=version,
        )

    def restore_rhythm(self, state: DurableFanState) -> PushPullEngine:
        rhythm = PushPullEngine()
        rhythm.phase_history = [
            RhythmPhase(value) for value in state.rhythm_phase_history
        ]
        rhythm.push_count = state.rhythm_push_count
        rhythm.pull_count = state.rhythm_pull_count
        return rhythm

    def has_processed(self, creator_id: str, platform_message_id: str) -> bool:
        stmt = select(PROCESSED_PLATFORM_MESSAGES.c.platform_message_id).where(
            and_(
                PROCESSED_PLATFORM_MESSAGES.c.creator_id == creator_id,
                PROCESSED_PLATFORM_MESSAGES.c.platform_message_id
                == platform_message_id,
            )
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar_one_or_none() is not None

    def get_poll_cursor(self, creator_id: str, scope: str) -> str | None:
        stmt = select(POLL_CURSORS.c.cursor).where(
            and_(
                POLL_CURSORS.c.creator_id == creator_id,
                POLL_CURSORS.c.scope == scope,
            )
        )
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar_one_or_none()

    def set_poll_cursor(
        self,
        creator_id: str,
        scope: str,
        cursor: str | None,
    ) -> None:
        self.ensure_creator(creator_id)
        now = utcnow()
        stmt = self._insert(POLL_CURSORS).values(
            creator_id=creator_id,
            scope=scope,
            cursor=cursor,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["creator_id", "scope"],
            set_={"cursor": cursor, "updated_at": now},
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def mark_processed(
        self,
        creator_id: str,
        platform_message_id: str,
        fan_id: str,
        chat_id: str | None,
    ) -> bool:
        self.ensure_creator(creator_id)
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    PROCESSED_PLATFORM_MESSAGES.insert().values(
                        creator_id=creator_id,
                        platform_message_id=platform_message_id,
                        fan_id=fan_id,
                        chat_id=chat_id,
                        processed_at=utcnow(),
                    )
                )
            return True
        except IntegrityError:
            return False

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
