"""Bounded memory and callback retrieval for one current turn."""

from __future__ import annotations

from datetime import datetime, timezone
import math

from src.conversation.brain2_repository import FanMemoryV2Repository
from src.conversation.intelligence_v3.knowledge import lexical_score, tokenize
from src.conversation.intelligence_v3.repository import IntelligenceRepository


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MemoryRetrieverV3:
    """Score approved active memory by usefulness, not raw recency alone."""

    def __init__(self, engine, *, creator_id: str):
        self.creator_id = creator_id
        self.memories = FanMemoryV2Repository(engine)
        self.intelligence = IntelligenceRepository(engine, creator_id=creator_id)

    def retrieve(
        self,
        *,
        fan_id: str,
        query: str,
        now: datetime,
        memory_limit: int = 10,
        callback_limit: int = 2,
    ) -> dict:
        terms = tokenize(query)
        candidates = self.memories.relevant(
            creator_id=self.creator_id,
            fan_id=fan_id,
            limit=100,
        )
        boundaries = []
        scored = []
        conflicts_excluded = 0
        for memory in candidates:
            if str(memory.get("contradiction_status") or "clear") != "clear":
                conflicts_excluded += 1
                continue
            age_days = max(
                0.0,
                (_aware(now) - _aware(memory["last_confirmed_at"])).total_seconds()
                / 86_400,
            )
            recency = math.exp(-age_days / 45.0)
            relevance = lexical_score(
                terms,
                f"{memory.get('memory_type', '')} {memory.get('display_value', '')}",
            )
            confidence = float(memory.get("confidence") or 0.0)
            importance = float(memory.get("importance") or 0.0)
            usefulness = _usefulness(memory.get("memory_type"))
            if str(memory.get("memory_type")) == "boundary":
                # Explicit fan boundaries are required context, not optional recall.
                relevance = 1.0
                boundaries.append(memory)
            score = relevance * confidence * importance * recency * usefulness
            scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = []
        maximum = max(8, min(int(memory_limit), 12))
        ordered = []
        seen_ids = set()
        for memory in boundaries:
            memory_id = int(memory["id"])
            if memory_id not in seen_ids:
                ordered.append((1.0, memory))
                seen_ids.add(memory_id)
        for score, memory in scored:
            memory_id = int(memory["id"])
            if memory_id in seen_ids or score <= 0:
                continue
            ordered.append((score, memory))
            seen_ids.add(memory_id)
            if len(ordered) >= maximum:
                break
        for score, memory in ordered[:maximum]:
            selected.append(
                {
                    "id": int(memory["id"]),
                    "type": str(memory["memory_type"]),
                    "value": str(memory["display_value"])[:500],
                    "confidence": round(float(memory["confidence"]), 4),
                    "score": round(score, 4),
                    "source_message_id": str(memory["source_message_id"])[:128],
                }
            )
        callbacks = self.intelligence.relevant_callbacks(
            fan_id=fan_id,
            limit=max(1, min(int(callback_limit), 2)),
        )
        return {
            "memories": selected,
            # Routing may use this count to force a strategic, fail-closed turn.
            # The conflicting values themselves never enter the prompt.
            "conflicts_excluded": conflicts_excluded,
            "callbacks": [
                {
                    "id": int(row["id"]),
                    "subject_key": str(row["subject_key"])[:128],
                    "subject": str(row["subject"])[:500],
                    "source_message_id": str(row["source_message_id"])[:128],
                    "sensitivity": str(row["emotional_sensitivity"]),
                    "times_referenced": int(row["times_referenced"] or 0),
                }
                for row in callbacks
            ],
        }


def _usefulness(memory_type: object) -> float:
    return {
        "boundary": 1.0,
        "correction": 1.0,
        "fan_promise": 0.95,
        "callback": 0.95,
        "emotional_sensitivity": 0.9,
        "relationship_event": 0.9,
        "preference": 0.85,
        "dislike": 0.85,
        "identity_fact": 0.8,
        "interest": 0.8,
        "recurring_life_event": 0.8,
        "fantasy_theme": 0.75,
        "uncertain_hypothesis": 0.4,
    }.get(str(memory_type), 0.7)
