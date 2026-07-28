"""Strict, reasoning-free response-plan contracts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any


BUBBLE_ROLES = frozenset(
    {
        "reaction",
        "answer",
        "validation",
        "personal_detail",
        "callback",
        "tease",
        "boundary",
        "question",
        "topic_shift",
    }
)
CASING_MODES = frozenset(
    {
        "standard",
        "mostly_lowercase",
        "mirror_fan",
        "high_energy",
        "serious",
    }
)
ENERGY_LEVELS = frozenset({"low", "medium", "high"})
FORBIDDEN_QUALITY_FLAGS = (
    "sales_intent",
    "media_intent",
    "ppv_intent",
    "tip_intent",
)


def _clean_text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum].strip()


@dataclass(frozen=True)
class DeliveryBubble:
    role: str
    text: str


@dataclass(frozen=True)
class HumanDeliveryDecision:
    """One validated decision with no private reasoning fields."""

    language: str
    fan_emotion: str
    relationship_stage: str
    unresolved_topic: str | None
    primary_act: str
    secondary_act: str | None
    should_ask_question: bool
    safety_class: str
    casing_mode: str
    energy: str
    bubbles: tuple[DeliveryBubble, ...]
    memory_updates: tuple[dict, ...]
    quality: dict

    @property
    def combined_text(self) -> str:
        return "\n".join(bubble.text for bubble in self.bubbles)

    @property
    def fingerprint(self) -> str:
        payload = {
            "language": self.language,
            "primary_act": self.primary_act,
            "casing_mode": self.casing_mode,
            "bubbles": [
                {"role": bubble.role, "text": bubble.text}
                for bubble in self.bubbles
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_model_output(
        cls,
        raw: str,
        *,
        max_bubbles: int = 3,
        conversation_only: bool = True,
    ) -> "HumanDeliveryDecision | None":
        normalized = str(raw or "").strip()
        fenced = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            normalized,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if fenced:
            normalized = fenced.group(1).strip()
        try:
            parsed = json.loads(normalized)
        except (TypeError, ValueError):
            return None
        if not isinstance(parsed, dict) or set(parsed) != {
            "understanding",
            "strategy",
            "delivery",
            "memory_updates",
            "quality",
        }:
            return None
        understanding = parsed["understanding"]
        strategy = parsed["strategy"]
        delivery = parsed["delivery"]
        quality = parsed["quality"]
        memory_updates = parsed["memory_updates"]
        if not all(
            isinstance(value, dict)
            for value in (understanding, strategy, delivery, quality)
        ) or not isinstance(memory_updates, list):
            return None
        raw_bubbles = delivery.get("bubbles")
        if (
            not isinstance(raw_bubbles, list)
            or not 1 <= len(raw_bubbles) <= min(max(int(max_bubbles), 1), 3)
        ):
            return None
        bubbles: list[DeliveryBubble] = []
        question_count = 0
        normalized_texts: set[str] = set()
        for item in raw_bubbles:
            if not isinstance(item, dict) or set(item) != {"role", "text"}:
                return None
            role = _clean_text(item.get("role"), 32).lower()
            text = _clean_text(item.get("text"), 500)
            if role not in BUBBLE_ROLES or not text:
                return None
            signature = re.sub(r"\W+", " ", text.casefold()).strip()
            if not signature or signature in normalized_texts:
                return None
            normalized_texts.add(signature)
            question_count += text.count("?")
            bubbles.append(DeliveryBubble(role=role, text=text))
        if question_count > 1:
            return None
        if bool(strategy.get("should_ask_question")) != bool(question_count):
            return None
        casing_mode = _clean_text(
            delivery.get("casing_mode"),
            32,
        ).lower()
        energy = _clean_text(delivery.get("energy"), 16).lower()
        safety_class = _clean_text(
            strategy.get("safety_class"),
            64,
        ).lower()
        if casing_mode not in CASING_MODES or energy not in ENERGY_LEVELS:
            return None
        if conversation_only:
            if safety_class != "conversation_only":
                return None
            if any(bool(quality.get(flag)) for flag in FORBIDDEN_QUALITY_FLAGS):
                return None
        if quality.get("facts_grounded") is not True:
            return None
        confidence = quality.get("confidence", 1.0)
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(float(confidence))
            or not 0 <= float(confidence) <= 1
        ):
            return None
        safe_updates = tuple(
            dict(item)
            for item in memory_updates[:20]
            if isinstance(item, dict)
            and "type" in item
            and "value" in item
            and "source_message_id" in item
        )
        return cls(
            language=_clean_text(understanding.get("language"), 16) or "en",
            fan_emotion=(
                _clean_text(understanding.get("fan_emotion"), 64)
                or "unknown"
            ),
            relationship_stage=(
                _clean_text(understanding.get("relationship_stage"), 64)
                or "unknown"
            ),
            unresolved_topic=(
                _clean_text(understanding.get("unresolved_topic"), 500)
                or None
            ),
            primary_act=(
                _clean_text(strategy.get("primary_act"), 64)
                or "direct_answer"
            ),
            secondary_act=(
                _clean_text(strategy.get("secondary_act"), 64)
                or None
            ),
            should_ask_question=bool(
                strategy.get("should_ask_question")
            ),
            safety_class=safety_class,
            casing_mode=casing_mode,
            energy=energy,
            bubbles=tuple(bubbles),
            memory_updates=safe_updates,
            quality=dict(quality),
        )
