"""Evidence-preserving Memory V2 ingestion and legacy backfill."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from src.conversation.brain2_repository import FanMemoryV2Repository
from src.notes.models import FanNote


class LegacyMemoryBackfill:
    """Copy flat notes without mutating or deleting their legacy source."""

    def __init__(self, repository: FanMemoryV2Repository):
        self.repository = repository

    def run(self, note: FanNote) -> int:
        existing = {
            item["normalized_value"]
            for item in self.repository.relevant(
                creator_id=note.creator_id,
                fan_id=note.fan_id,
                limit=100,
            )
        }
        candidates: list[tuple[str, str, float, float]] = []
        candidates.extend(
            ("preference", value, 0.75, 0.65)
            for value in (note.preferences or [])
        )
        candidates.extend(
            ("boundary", value, 1.0, 1.0)
            for value in (note.hard_limits or [])
        )
        candidates.extend(
            ("personal_fact", value, 0.65, 0.55)
            for value in (note.facts or [])
        )
        created = 0
        now = datetime.now(timezone.utc)
        for memory_type, display, confidence, importance in candidates:
            display = str(display).strip()
            if not display:
                continue
            normalized = f"{memory_type}:{display.casefold()}"
            if normalized in existing:
                continue
            digest = hashlib.sha256(
                (
                    f"{note.creator_id}:{note.fan_id}:"
                    f"{normalized}"
                ).encode()
            ).hexdigest()[:24]
            self.repository.remember(
                creator_id=note.creator_id,
                fan_id=note.fan_id,
                memory_type=memory_type,
                normalized_value=normalized,
                display_value=display,
                confidence=confidence,
                importance=importance,
                source_message_id=f"legacy-note:{digest}",
                source_timestamp=note.first_contact_at or now,
                expires_at=None,
            )
            existing.add(normalized)
            created += 1
        return created


class ExtractedMemoryWriter:
    """Persist extracted values with the exact source message evidence."""

    _TYPE_MAP = {
        "preferences": "preference",
        "hard_limits": "boundary",
        "facts": "personal_fact",
        "occupation": "personal_fact",
        "emotional_triggers": "relationship_event",
    }

    def __init__(self, repository: FanMemoryV2Repository):
        self.repository = repository

    def write(
        self,
        *,
        creator_id: str,
        fan_id: str,
        extracted: dict,
        source_message_id: str,
        source_timestamp: datetime,
    ) -> int:
        written = 0
        for key, raw in extracted.items():
            memory_type = self._TYPE_MAP.get(key)
            if memory_type is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                display = str(value or "").strip()
                if not display:
                    continue
                normalized = f"{key}:{display.casefold()}"
                self.repository.remember(
                    creator_id=creator_id,
                    fan_id=fan_id,
                    memory_type=memory_type,
                    normalized_value=normalized,
                    display_value=display,
                    confidence=0.7,
                    importance=1.0 if memory_type == "boundary" else 0.6,
                    source_message_id=source_message_id,
                    source_timestamp=source_timestamp,
                    contradiction_key=(
                        key if key in {"occupation"} else None
                    ),
                    expires_at=None,
                )
                written += 1
        return written
