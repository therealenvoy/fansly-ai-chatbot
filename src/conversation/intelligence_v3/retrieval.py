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
        scored = []
        for memory in candidates:
            if str(memory.get("contradiction_status") or "clear") != "clear":
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
            usefulness = 1.0 if memory.get("memory_key") else 0.7
            score = (
                0.35 * relevance
                + 0.2 * confidence
                + 0.2 * importance
                + 0.15 * recency
                + 0.1 * usefulness
            )
            scored.append((score, memory))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = []
        for score, memory in scored[: max(1, min(int(memory_limit), 12))]:
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
            "callbacks": [
                {
                    "id": int(row["id"]),
                    "subject": str(row["subject"])[:500],
                    "source_message_id": str(row["source_message_id"])[:128],
                    "sensitivity": str(row["emotional_sensitivity"]),
                    "times_referenced": int(row["times_referenced"] or 0),
                }
                for row in callbacks
            ],
        }
