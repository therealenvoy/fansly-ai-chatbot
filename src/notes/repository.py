"""FanNoteRepository — SQLAlchemy Core storage with dialect-aware upserts."""

import json
from datetime import datetime
from sqlalchemy import MetaData
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from src.notes.models import FanNote
from src.persistence.database import create_database_engine
from src.persistence.schema import FAN_NOTES


FAN_NOTES_TABLE = FAN_NOTES


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
    """SQLAlchemy repository for FanNote with a shared-engine option."""

    def __init__(self, db_url: str | None = None, *, engine=None):
        if engine is None and db_url is None:
            raise ValueError("db_url or engine is required")
        self.engine = engine or create_database_engine(db_url)
        self.metadata = MetaData()

    def create_table(self):
        """Create the table for isolated tests; production uses Alembic."""
        FAN_NOTES_TABLE.create(self.engine, checkfirst=True)

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
