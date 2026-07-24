"""
Tests for FanNoteRepository — SQLite-backed upsert storage.

Strict TDD: RED → GREEN → REFACTOR cycle.
"""

import pytest
from datetime import datetime
from src.notes.models import FanNote
from src.notes.repository import FanNoteRepository


class TestFanNoteRepository:
    """FanNoteRepository: save, get, upsert behavior."""

    @pytest.fixture
    def repo(self):
        """Create repository backed by in-memory SQLite."""
        repo = FanNoteRepository(db_url="sqlite:///:memory:")
        repo.create_table()
        return repo

    def test_create_table(self, repo):
        """create_table should execute without error."""
        # If we reach here without exception, the table exists.
        # Verify by saving and loading.
        note = FanNote(fan_id="f1", creator_id="c1")
        repo.save(note)
        loaded = repo.get("f1", "c1")
        assert loaded is not None
        assert loaded.fan_id == "f1"

    def test_save_and_load_note(self, repo):
        """Save a note and load it back, verifying all fields."""
        now = datetime(2026, 7, 24, 12, 0, 0)
        note = FanNote(
            fan_id="fan_save_1",
            creator_id="creator_1",
            display_name="Alice",
            preferences=["lingerie", "roleplay"],
            occupation="nurse",
            total_spent=250.0,
            purchase_count=5,
            last_purchase_at=now,
            emotional_triggers=["compliments"],
            hard_limits=["scat"],
            notes="Frequent buyer",
            first_contact_at=datetime(2025, 6, 1),
            relationship_stage="regular",
        )

        repo.save(note)
        loaded = repo.get("fan_save_1", "creator_1")

        assert loaded is not None
        assert loaded.fan_id == "fan_save_1"
        assert loaded.creator_id == "creator_1"
        assert loaded.display_name == "Alice"
        assert loaded.preferences == ["lingerie", "roleplay"]
        assert loaded.occupation == "nurse"
        assert loaded.total_spent == 250.0
        assert loaded.purchase_count == 5
        assert loaded.last_purchase_at == now
        assert loaded.emotional_triggers == ["compliments"]
        assert loaded.hard_limits == ["scat"]
        assert loaded.notes == "Frequent buyer"
        assert loaded.first_contact_at == datetime(2025, 6, 1)
        assert loaded.relationship_stage == "regular"

    def test_get_nonexistent_returns_none(self, repo):
        """get with non-existent key should return None."""
        result = repo.get("nonexistent", "nonexistent")
        assert result is None

    def test_save_is_upsert(self, repo):
        """Saving with the same fan_id+creator_id updates the existing row."""
        note1 = FanNote(
            fan_id="fan_upsert",
            creator_id="creator_1",
            display_name="Original",
            total_spent=50.0,
        )
        repo.save(note1)

        note2 = FanNote(
            fan_id="fan_upsert",
            creator_id="creator_1",
            display_name="Updated",
            total_spent=500.0,
        )
        repo.save(note2)

        loaded = repo.get("fan_upsert", "creator_1")
        assert loaded is not None
        assert loaded.display_name == "Updated"
        assert loaded.total_spent == 500.0

    def test_update_note_merges_fields(self, repo):
        """Save, modify, save again, verify merged — old fields preserved
        when not overwritten in the second save."""
        note = FanNote(
            fan_id="fan_merge",
            creator_id="creator_1",
            display_name="Bob",
            preferences=["cosplay"],
            occupation="teacher",
            total_spent=100.0,
            purchase_count=3,
        )
        repo.save(note)

        # Update only some fields
        updated = FanNote(
            fan_id="fan_merge",
            creator_id="creator_1",
            display_name="Bob",
            preferences=["cosplay", "feet"],  # added
            occupation="teacher",
            total_spent=300.0,  # increased
            purchase_count=5,  # increased
        )
        repo.save(updated)

        loaded = repo.get("fan_merge", "creator_1")
        assert loaded is not None
        assert loaded.display_name == "Bob"
        assert loaded.preferences == ["cosplay", "feet"]
        assert loaded.occupation == "teacher"
        assert loaded.total_spent == 300.0
        assert loaded.purchase_count == 5