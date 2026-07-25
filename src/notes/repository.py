"""FanNoteRepository — SQLAlchemy Core + SQLite storage with upsert support."""

import json
from datetime import datetime
from sqlalchemy import (
    create_engine, MetaData, Table, Column, String, Float, Integer,
    DateTime, Text, text
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from src.notes.models import FanNote


FAN_NOTES_TABLE = Table(
    "fan_notes",
    MetaData(),
    Column("fan_id", String, primary_key=True),
    Column("creator_id", String, primary_key=True),
    Column("display_name", String, nullable=True),
    Column("preferences", Text, default="[]"),
    Column("occupation", String, nullable=True),
    Column("total_spent", Float, default=0.0),
    Column("purchase_count", Integer, default=0),
    Column("last_purchase_at", DateTime, nullable=True),
    Column("emotional_triggers", Text, default="[]"),
    Column("hard_limits", Text, default="[]"),
    Column("facts", Text, default="[]"),
    Column("notes", Text, default=""),
    Column("first_contact_at", DateTime, nullable=True),
    Column("relationship_stage", String, default="new"),
)


def _note_to_row(note: FanNote) -> dict:
    """Convert FanNote to row dict for DB insertion."""
    return {
        "fan_id": note.fan_id,
        "creator_id": note.creator_id,
        "display_name": note.display_name,
        "preferences": json.dumps(note.preferences),
        "occupation": note.occupation,
        "total_spent": note.total_spent,
        "purchase_count": note.purchase_count,
        "last_purchase_at": note.last_purchase_at,
        "emotional_triggers": json.dumps(note.emotional_triggers),
        "hard_limits": json.dumps(note.hard_limits),
        "facts": json.dumps(note.facts),
        "notes": note.notes,
        "first_contact_at": note.first_contact_at,
        "relationship_stage": note.relationship_stage,
    }


def _row_to_note(row) -> FanNote:
    """Convert DB row to FanNote."""
    row_dict = dict(row._mapping)
    # Parse JSON list columns
    row_dict["preferences"] = json.loads(row_dict.get("preferences", "[]") or "[]")
    row_dict["emotional_triggers"] = json.loads(row_dict.get("emotional_triggers", "[]") or "[]")
    row_dict["hard_limits"] = json.loads(row_dict.get("hard_limits", "[]") or "[]")
    row_dict["facts"] = json.loads(row_dict.get("facts", "[]") or "[]")
    return FanNote(**row_dict)


class FanNoteRepository:
    """SQLite-backed repository for FanNote with upsert (fan_id + creator_id composite key)."""

    def __init__(self, db_url: str):
        self.engine = create_engine(db_url)
        self.metadata = MetaData()

    def create_table(self):
        """Create the fan_notes table if it doesn't exist, and migrate new columns."""
        FAN_NOTES_TABLE.create(self.engine, checkfirst=True)
        # Dialect-agnostic migration: add columns introduced after initial deploys.
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(self.engine)
        try:
            existing = {c["name"] for c in insp.get_columns("fan_notes")}
        except Exception:
            existing = set()
        with self.engine.connect() as conn:
            for col, ddl in [("facts", "TEXT DEFAULT '[]'")]:
                if col not in existing:
                    conn.execute(
                        text(f"ALTER TABLE fan_notes ADD COLUMN {col} {ddl}")
                    )
            conn.commit()

    def save(self, note: FanNote):
        """Upsert a FanNote (fan_id + creator_id as composite key)."""
        row = _note_to_row(note)
        set_dict = {
            "display_name": "display_name",
            "preferences": "preferences",
            "occupation": "occupation",
            "total_spent": "total_spent",
            "purchase_count": "purchase_count",
            "last_purchase_at": "last_purchase_at",
            "emotional_triggers": "emotional_triggers",
            "hard_limits": "hard_limits",
            "facts": "facts",
            "notes": "notes",
            "first_contact_at": "first_contact_at",
            "relationship_stage": "relationship_stage",
        }
        if self.engine.dialect.name == "postgresql":
            stmt = pg_insert(FAN_NOTES_TABLE).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["fan_id", "creator_id"],
                set_={k: getattr(stmt.excluded, k) for k in set_dict},
            )
        else:
            stmt = sqlite_insert(FAN_NOTES_TABLE).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["fan_id", "creator_id"],
                set_={k: getattr(stmt.excluded, k) for k in set_dict},
            )
        with self.engine.connect() as conn:
            conn.execute(stmt)
            conn.commit()

    def get(self, fan_id: str, creator_id: str) -> FanNote | None:
        """Retrieve a FanNote by fan_id and creator_id, or None if not found."""
        stmt = FAN_NOTES_TABLE.select().where(
            (FAN_NOTES_TABLE.c.fan_id == fan_id)
            & (FAN_NOTES_TABLE.c.creator_id == creator_id)
        )
        with self.engine.connect() as conn:
            result = conn.execute(stmt)
            row = result.first()
            if row is None:
                return None
            return _row_to_note(row)