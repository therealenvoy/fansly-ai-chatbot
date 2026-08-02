"""Bounded memory and callback retrieval for one current turn."""

from __future__ import annotations

from datetime import datetime, timezone
import math

from src.conversation.brain2_repository import FanMemoryV2Repository
from src.conversation.intelligence_v3.knowledge import lexical_score, tokenize
from src.conversation.intelligence_v3.repository import (
    IntelligenceRepository,
    KnowledgeRepository,
)


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
        self.knowledge = KnowledgeRepository(engine, creator_id=creator_id)

    def retrieve(
        self,
        *,
        fan_id: str,
        query: str,
        now: datetime,
        memory_limit: int = 10,
        callback_limit: int = 2,
        shadow: bool = False,
    ) -> dict:
        terms = tokenize(query)
        release = self.knowledge.active_corpus_release(shadow=shadow)
        runtime_manifest = dict((release or {}).get("runtime_manifest") or {})
        policy = dict(runtime_manifest.get("memory_policy") or {})
        categories = dict(policy.get("categories") or {})
        minimum_confidence = float(policy.get("minimum_durable_confidence") or 0.0)
        candidates = self.memories.relevant(
            creator_id=self.creator_id,
            fan_id=fan_id,
            limit=100,
        )
        boundaries = []
        scored = []
        controls = []
        conflicts_excluded = 0
        for memory in candidates:
            if str(memory.get("contradiction_status") or "clear") != "clear":
                conflicts_excluded += 1
                continue
            category = _policy_category(memory.get("memory_type"))
            category_policy = dict(categories.get(category) or {})
            if categories and not category_policy:
                # Part 09 is an allowlist: unknown and speculative memory never
                # becomes prompt evidence merely because an older writer stored it.
                continue
            confidence = float(memory.get("confidence") or 0.0)
            if confidence < minimum_confidence:
                continue
            mention = str(category_policy.get("mention") or "yes")
            if mention == "no":
                continue
            relevance = lexical_score(
                terms,
                f"{category} {memory.get('display_value', '')}",
            )
            if mention == "contextual" and relevance <= 0:
                continue
            if mention == "operator_only":
                controls.append(
                    {
                        "id": int(memory["id"]),
                        "category": category,
                        "instruction": str(memory["display_value"])[:500],
                        "confidence": round(confidence, 4),
                        "do_not_quote": True,
                        "source_message_id": str(memory["source_message_id"])[:128],
                    }
                )
                continue
            age_days = max(
                0.0,
                (_aware(now) - _aware(memory["last_confirmed_at"])).total_seconds()
                / 86_400,
            )
            recency = math.exp(-age_days / 45.0)
            importance = float(memory.get("importance") or 0.0)
            usefulness = _usefulness(category)
            if category == "boundary":
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
            selected_category = _policy_category(memory.get("memory_type"))
            selected.append(
                {
                    "id": int(memory["id"]),
                    "type": selected_category,
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
            "controls": controls[:12],
            "policy_version": str(policy.get("policy_version") or "legacy"),
            "release": (
                {
                    "release_key": release["release_key"],
                    "version": release["version"],
                    "manifest_fingerprint": release["manifest_fingerprint"],
                }
                if release
                else None
            ),
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
        "promised_callback": 0.95,
        "open_thread": 0.95,
        "emotional_sensitivity": 0.9,
        "life_event": 0.9,
        "preference": 0.85,
        "dislike": 0.85,
        "verified_personal_fact": 0.8,
        "interest": 0.8,
        "work_and_schedule": 0.8,
        "important_person": 0.8,
        "recurring_concern": 0.85,
    }.get(str(memory_type), 0.7)


def _policy_category(memory_type: object) -> str:
    value = str(memory_type or "")
    return {
        "identity_fact": "verified_personal_fact",
        "recurring_life_event": "life_event",
        "relationship_event": "life_event",
        "fan_promise": "promised_callback",
        "callback": "open_thread",
        "dislike": "preference",
        "fantasy_theme": "preference",
    }.get(value, value)
