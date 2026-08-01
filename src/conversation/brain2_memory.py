"""Evidence-preserving Memory V2 ingestion and legacy backfill."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    _ALLOWED_V3_TYPES = frozenset(
        {
            "identity_fact",
            "interest",
            "preference",
            "dislike",
            "boundary",
            "recurring_life_event",
            "emotional_sensitivity",
            "relationship_event",
            "fan_promise",
            "correction",
            "callback",
            "fantasy_theme",
            "uncertain_hypothesis",
        }
    )
    _SENSITIVITY = frozenset({"standard", "sensitive", "private"})

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
        structured_values = {
            str(candidate.get("value") or "").strip().casefold()
            for candidate in extracted.get("memory_candidates", [])
            if isinstance(candidate, dict)
            and str(candidate.get("value") or "").strip()
        }
        for key, raw in extracted.items():
            if key == "memory_candidates":
                written += self._write_candidates(
                    creator_id=creator_id,
                    fan_id=fan_id,
                    candidates=raw,
                    source_message_id=source_message_id,
                    source_timestamp=source_timestamp,
                )
                continue
            memory_type = self._TYPE_MAP.get(key)
            if memory_type is None:
                continue
            values = raw if isinstance(raw, list) else [raw]
            for value in values:
                display = str(value or "").strip()
                if not display:
                    continue
                # The model can return both the legacy compatibility fields and
                # the richer V3 candidate for the same source-backed fact. Store
                # the richer record once instead of creating two differently
                # keyed memories from one sentence.
                if display.casefold() in structured_values:
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

    def _write_candidates(
        self,
        *,
        creator_id: str,
        fan_id: str,
        candidates: object,
        source_message_id: str,
        source_timestamp: datetime,
    ) -> int:
        if not isinstance(candidates, list):
            return 0
        written = 0
        for candidate in candidates[:24]:
            if not isinstance(candidate, dict):
                continue
            memory_type = str(candidate.get("type") or "").strip()
            display = str(candidate.get("value") or "").strip()
            if memory_type not in self._ALLOWED_V3_TYPES or not display:
                continue
            confidence = _bounded_number(candidate.get("confidence"), default=0.6)
            importance = _bounded_number(candidate.get("importance"), default=0.5)
            if memory_type == "uncertain_hypothesis":
                confidence = min(confidence, 0.69)
            if memory_type in {"boundary", "correction"}:
                confidence = 1.0
                importance = 1.0
            sensitivity = str(
                candidate.get("sensitivity_class") or "standard"
            ).strip()
            if sensitivity not in self._SENSITIVITY:
                sensitivity = "standard"
            if memory_type in {"fantasy_theme", "emotional_sensitivity"}:
                sensitivity = "private" if sensitivity == "standard" else sensitivity
            contradiction_key = str(
                candidate.get("contradiction_key") or ""
            ).strip()[:128] or None
            if memory_type == "correction" and contradiction_key is None:
                # A correction without a target cannot safely supersede anything.
                continue
            temporary_days = _temporary_days(candidate.get("temporary_days"))
            expires_at = (
                _aware(source_timestamp) + timedelta(days=temporary_days)
                if temporary_days is not None
                else None
            )
            self.repository.remember(
                creator_id=creator_id,
                fan_id=fan_id,
                memory_type=memory_type,
                normalized_value=f"{memory_type}:{display.casefold()}",
                display_value=display[:2_000],
                confidence=confidence,
                importance=importance,
                source_message_id=source_message_id,
                source_timestamp=source_timestamp,
                contradiction_key=contradiction_key,
                expires_at=expires_at,
                sensitivity_class=sensitivity,
                supersede_across_types=memory_type == "correction",
            )
            written += 1
        return written


def _bounded_number(value: object, *, default: float) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return default


def _temporary_days(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return max(1, min(int(value), 365))
    except (TypeError, ValueError):
        return None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
