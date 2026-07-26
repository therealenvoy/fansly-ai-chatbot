"""SequenceRepository — SQLAlchemy Core persistence for PPV sequences.

Follows the same pattern as FanNoteRepository: pure SQLAlchemy Core,
dialect-aware upserts, simple Table definitions.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from src.persistence.database import create_database_engine
from src.persistence.schema import (
    PPV_FAN_PROGRESS,
    PPV_SEQUENCES,
    PPV_SEQUENCE_STEPS,
)

from .models import (
    Sequence, SequenceStep, FanSequenceProgress,
    SequenceTrigger, StepStatus,
)

logger = logging.getLogger(__name__)

# ─── TABLE DEFINITIONS ─────────────────────────────────────

SEQUENCES_TABLE = PPV_SEQUENCES
STEPS_TABLE = PPV_SEQUENCE_STEPS
PROGRESS_TABLE = PPV_FAN_PROGRESS


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

    def __init__(self, db_url: str | None = None, *, engine=None):
        if engine is None and db_url is None:
            raise ValueError("db_url or engine is required")
        self.engine = engine or create_database_engine(db_url)

    def create_tables(self):
        """Create tables for isolated tests; production uses Alembic."""
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

    def save_sequence_with_steps(self, seq: Sequence) -> Sequence:
        """Atomically save a sequence and replace its ordered steps."""
        sequence_values = {
            "name": seq.name,
            "trigger": seq.trigger.value,
            "funnel_stage": seq.funnel_stage,
            "is_active": seq.is_active,
        }
        original_id = seq.id
        try:
            with self.engine.begin() as conn:
                if seq.id is None:
                    result = conn.execute(
                        SEQUENCES_TABLE.insert().values(
                            **sequence_values
                        )
                    )
                    seq.id = result.inserted_primary_key[0]
                else:
                    result = conn.execute(
                        SEQUENCES_TABLE.update()
                        .where(SEQUENCES_TABLE.c.id == seq.id)
                        .values(**sequence_values)
                    )
                    if result.rowcount != 1:
                        raise ValueError(
                            f"Sequence {seq.id} does not exist"
                        )
                    conn.execute(
                        STEPS_TABLE.delete().where(
                            STEPS_TABLE.c.sequence_id == seq.id
                        )
                    )

                saved_steps = []
                for position, step in enumerate(
                    sorted(
                        seq.steps,
                        key=lambda item: item.position,
                    ),
                    start=1,
                ):
                    result = conn.execute(
                        STEPS_TABLE.insert().values(
                            sequence_id=seq.id,
                            position=position,
                            media_id=step.media_id,
                            preview_id=step.preview_id,
                            price=step.price,
                            tease_script=step.tease_script,
                            offer_script=step.offer_script,
                        )
                    )
                    step.id = result.inserted_primary_key[0]
                    step.sequence_id = seq.id
                    step.position = position
                    saved_steps.append(step)
                seq.steps = saved_steps
        except Exception:
            seq.id = original_id
            raise
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

    def delete_sequence(self, sequence_id: int) -> bool:
        """Delete a sequence and its dependent rows, returning whether it existed."""
        with self.engine.begin() as conn:
            exists = conn.execute(
                SEQUENCES_TABLE.select()
                .where(SEQUENCES_TABLE.c.id == sequence_id)
                .with_only_columns(SEQUENCES_TABLE.c.id)
            ).first()
            if exists is None:
                return False
            conn.execute(STEPS_TABLE.delete().where(STEPS_TABLE.c.sequence_id == sequence_id))
            conn.execute(PROGRESS_TABLE.delete().where(PROGRESS_TABLE.c.sequence_id == sequence_id))
            conn.execute(SEQUENCES_TABLE.delete().where(SEQUENCES_TABLE.c.id == sequence_id))
        return True

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
