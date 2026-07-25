"""SequenceRepository — SQLAlchemy Core persistence for PPV sequences.

Follows the same pattern as FanNoteRepository: pure SQLAlchemy Core,
dialect-aware upserts, simple Table definitions.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    create_engine, MetaData, Table, Column, String, Float, Integer,
    DateTime, Text, Boolean, UniqueConstraint, desc
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .models import (
    Sequence, SequenceStep, FanSequenceProgress,
    SequenceTrigger, StepStatus,
)

logger = logging.getLogger(__name__)

# ─── TABLE DEFINITIONS ─────────────────────────────────────

SEQUENCES_TABLE = Table(
    "ppv_sequences",
    MetaData(),
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("trigger", String, nullable=False),           # SequenceTrigger enum value
    Column("funnel_stage", String, nullable=False, default="rapport"),
    Column("is_active", Boolean, default=True),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
)

STEPS_TABLE = Table(
    "ppv_sequence_steps",
    MetaData(),
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sequence_id", Integer, nullable=False),
    Column("position", Integer, nullable=False),           # 1-based ordering
    Column("media_id", String, nullable=False),
    Column("preview_id", String, nullable=True),
    Column("price", Float, nullable=False),
    Column("tease_script", Text, default=""),
    Column("offer_script", Text, default=""),
    Column("created_at", DateTime, default=lambda: datetime.now(timezone.utc)),
)

PROGRESS_TABLE = Table(
    "ppv_fan_progress",
    MetaData(),
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fan_id", String, nullable=False),
    Column("sequence_id", Integer, nullable=False),
    Column("creator_id", String, nullable=False),
    Column("current_step", Integer, default=0),
    Column("status", String, default=StepStatus.PENDING.value),
    Column("last_sent_at", DateTime, nullable=True),
    Column("bought_at", DateTime, nullable=True),
    Column("started_at", DateTime, default=lambda: datetime.now(timezone.utc)),
    # Composite unique for upsert
    UniqueConstraint("fan_id", "sequence_id", "creator_id", name="uq_fan_seq_progress"),
)


# ─── CONVERTERS ────────────────────────────────────────────

def _row_to_sequence(row) -> Sequence:
    d = dict(row._mapping)
    return Sequence(
        id=d["id"],
        name=d["name"],
        trigger=SequenceTrigger(d["trigger"]),
        funnel_stage=d.get("funnel_stage", "rapport"),
        is_active=bool(d.get("is_active", True)),
        created_at=d.get("created_at", datetime.now(timezone.utc)),
    )


def _step_row_to_step(row) -> SequenceStep:
    d = dict(row._mapping)
    return SequenceStep(
        id=d["id"],
        sequence_id=d["sequence_id"],
        position=d["position"],
        media_id=d["media_id"],
        preview_id=d.get("preview_id"),
        price=float(d["price"]),
        tease_script=d.get("tease_script", "") or "",
        offer_script=d.get("offer_script", "") or "",
        created_at=d.get("created_at", datetime.now(timezone.utc)),
    )


def _progress_row_to_progress(row) -> FanSequenceProgress:
    d = dict(row._mapping)
    return FanSequenceProgress(
        id=d["id"],
        fan_id=d["fan_id"],
        sequence_id=d["sequence_id"],
        creator_id=d["creator_id"],
        current_step=d.get("current_step", 0),
        status=StepStatus(d.get("status", StepStatus.PENDING.value)),
        last_sent_at=d.get("last_sent_at"),
        bought_at=d.get("bought_at"),
        started_at=d.get("started_at", datetime.now(timezone.utc)),
    )


# ─── REPOSITORY ────────────────────────────────────────────

class SequenceRepository:
    """SQLite/Postgres repository for PPV sequences, steps, and fan progress."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)

    def create_tables(self):
        """Create all sequence tables if they don't exist."""
        SEQUENCES_TABLE.create(self.engine, checkfirst=True)
        STEPS_TABLE.create(self.engine, checkfirst=True)
        PROGRESS_TABLE.create(self.engine, checkfirst=True)

    # ─── SEQUENCES ─────────────────────────────────────

    def save_sequence(self, seq: Sequence) -> Sequence:
        """Insert or update a sequence."""
        values = {
            "name": seq.name,
            "trigger": seq.trigger.value,
            "funnel_stage": seq.funnel_stage,
            "is_active": seq.is_active,
        }
        if seq.id is not None:
            # Update
            with self.engine.connect() as conn:
                conn.execute(
                    SEQUENCES_TABLE.update().where(SEQUENCES_TABLE.c.id == seq.id).values(**values)
                )
                conn.commit()
            return seq
        # Insert
        with self.engine.connect() as conn:
            result = conn.execute(SEQUENCES_TABLE.insert().values(**values))
            conn.commit()
            seq.id = result.inserted_primary_key[0]

        # Save steps if any
        for step in seq.steps:
            step.sequence_id = seq.id
            self.save_step(step)

        return seq

    def get_sequence(self, sequence_id: int) -> Optional[Sequence]:
        with self.engine.connect() as conn:
            row = conn.execute(
                SEQUENCES_TABLE.select().where(SEQUENCES_TABLE.c.id == sequence_id)
            ).first()
            if not row:
                return None
            seq = _row_to_sequence(row)
            seq.steps = self.get_steps(sequence_id)
            return seq

    def list_sequences(self, active_only: bool = False) -> list[Sequence]:
        stmt = SEQUENCES_TABLE.select()
        if active_only:
            stmt = stmt.where(SEQUENCES_TABLE.c.is_active == True)
        stmt = stmt.order_by(desc(SEQUENCES_TABLE.c.created_at))
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        sequences = [_row_to_sequence(r) for r in rows]
        # Load steps for each
        for sq in sequences:
            sq.steps = self.get_steps(sq.id)
        return sequences

    def delete_sequence(self, sequence_id: int):
        """Delete a sequence and all its steps + progress records."""
        with self.engine.connect() as conn:
            conn.execute(STEPS_TABLE.delete().where(STEPS_TABLE.c.sequence_id == sequence_id))
            conn.execute(PROGRESS_TABLE.delete().where(PROGRESS_TABLE.c.sequence_id == sequence_id))
            conn.execute(SEQUENCES_TABLE.delete().where(SEQUENCES_TABLE.c.id == sequence_id))
            conn.commit()

    # ─── STEPS ─────────────────────────────────────────

    def save_step(self, step: SequenceStep) -> SequenceStep:
        values = {
            "sequence_id": step.sequence_id,
            "position": step.position,
            "media_id": step.media_id,
            "preview_id": step.preview_id,
            "price": step.price,
            "tease_script": step.tease_script,
            "offer_script": step.offer_script,
        }
        if step.id is not None:
            with self.engine.connect() as conn:
                conn.execute(
                    STEPS_TABLE.update().where(STEPS_TABLE.c.id == step.id).values(**values)
                )
                conn.commit()
            return step
        with self.engine.connect() as conn:
            result = conn.execute(STEPS_TABLE.insert().values(**values))
            conn.commit()
            step.id = result.inserted_primary_key[0]
        return step

    def get_steps(self, sequence_id: int) -> list[SequenceStep]:
        stmt = STEPS_TABLE.select().where(STEPS_TABLE.c.sequence_id == sequence_id).order_by(STEPS_TABLE.c.position)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_step_row_to_step(r) for r in rows]

    def delete_step(self, step_id: int):
        with self.engine.connect() as conn:
            conn.execute(STEPS_TABLE.delete().where(STEPS_TABLE.c.id == step_id))
            conn.commit()

    def reorder_steps(self, sequence_id: int, step_ids: list[int]):
        """Reorder steps by setting positions based on list order (1-based)."""
        with self.engine.connect() as conn:
            for pos, step_id in enumerate(step_ids, start=1):
                conn.execute(
                    STEPS_TABLE.update().where(STEPS_TABLE.c.id == step_id).values(position=pos)
                )
            conn.commit()

    # ─── FAN PROGRESS ──────────────────────────────────

    def save_progress(self, progress: FanSequenceProgress) -> FanSequenceProgress:
        values = {
            "fan_id": progress.fan_id,
            "sequence_id": progress.sequence_id,
            "creator_id": progress.creator_id,
            "current_step": progress.current_step,
            "status": progress.status.value,
            "last_sent_at": progress.last_sent_at,
            "bought_at": progress.bought_at,
        }
        if progress.id is not None:
            with self.engine.connect() as conn:
                conn.execute(
                    PROGRESS_TABLE.update().where(PROGRESS_TABLE.c.id == progress.id).values(**values)
                )
                conn.commit()
            return progress

        # Insert with upsert for idempotency
        if self.engine.dialect.name == "postgresql":
            stmt = pg_insert(PROGRESS_TABLE).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["fan_id", "sequence_id", "creator_id"],
                set_={
                    "current_step": stmt.excluded.current_step,
                    "status": stmt.excluded.status,
                    "last_sent_at": stmt.excluded.last_sent_at,
                    "bought_at": stmt.excluded.bought_at,
                },
            )
        else:
            stmt = sqlite_insert(PROGRESS_TABLE).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["fan_id", "sequence_id", "creator_id"],
                set_={
                    "current_step": stmt.excluded.current_step,
                    "status": stmt.excluded.status,
                    "last_sent_at": stmt.excluded.last_sent_at,
                    "bought_at": stmt.excluded.bought_at,
                },
            )
        with self.engine.connect() as conn:
            result = conn.execute(stmt)
            conn.commit()
            if progress.id is None:
                progress.id = result.inserted_primary_key[0]
        return progress

    def get_progress(self, fan_id: str, sequence_id: int, creator_id: str) -> Optional[FanSequenceProgress]:
        stmt = PROGRESS_TABLE.select().where(
            (PROGRESS_TABLE.c.fan_id == fan_id)
            & (PROGRESS_TABLE.c.sequence_id == sequence_id)
            & (PROGRESS_TABLE.c.creator_id == creator_id)
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
            return _progress_row_to_progress(row) if row else None

    def get_fan_progress(self, fan_id: str, creator_id: str) -> list[FanSequenceProgress]:
        stmt = PROGRESS_TABLE.select().where(
            (PROGRESS_TABLE.c.fan_id == fan_id)
            & (PROGRESS_TABLE.c.creator_id == creator_id)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_progress_row_to_progress(r) for r in rows]

    def get_active_sequences_for_fan(self, fan_id: str, creator_id: str) -> list[Sequence]:
        """Get all active sequences the fan hasn't completed (not BOUGHT on final step)."""
        all_active = self.list_sequences(active_only=True)
        # Get fan's progress for all of them
        fan_seqs = {p.sequence_id: p for p in self.get_fan_progress(fan_id, creator_id)}

        result = []
        for seq in all_active:
            seq_id = seq.id
            p = fan_seqs.get(seq_id)
            if p and p.status == StepStatus.BOUGHT:
                # Fan completed this sequence
                continue
            result.append(seq)
        return result