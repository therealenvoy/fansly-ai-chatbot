"""Structured conversation planning contracts for autonomous chat mode."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import re
from typing import Any


OBJECTIVES = frozenset(
    {
        "answer",
        "reconnect",
        "deepen",
        "support",
        "learn",
        "play",
        "repair",
        "maintain",
    }
)
TACTICS = frozenset(
    {
        "direct_answer",
        "specific_follow_up",
        "callback",
        "validation",
        "playful_challenge",
        "gentle_check_in",
        "open_question",
    }
)


def _text(value: Any, maximum: int) -> str:
    normalized = str(value or "").strip()
    return normalized[:maximum].strip()


def _json_object(raw: str) -> dict[str, Any] | None:
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
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True)
class ConversationDecision:
    """One auditable plan, critique, and final message."""

    fan_state: str
    state_summary: str
    objective: str
    tactic: str
    open_thread: str | None
    draft: str
    critique: tuple[str, ...]
    final_message: str
    confidence: float

    def with_approved_message(self, message: str) -> "ConversationDecision":
        return replace(self, final_message=_text(message, 2_000))

    @classmethod
    def from_model_output(
        cls,
        raw: str,
        *,
        proactive_kind: str | None,
        strict: bool = False,
    ) -> "ConversationDecision | None":
        parsed = _json_object(raw)
        if strict and parsed is not None:
            required = {
                "fan_state",
                "state_summary",
                "objective",
                "tactic",
                "open_thread",
                "draft",
                "critique",
                "final_message",
                "confidence",
            }
            if set(parsed) != required:
                return None
            if not all(
                isinstance(parsed[field], str)
                for field in (
                    "fan_state",
                    "state_summary",
                    "objective",
                    "tactic",
                    "draft",
                    "final_message",
                )
            ):
                return None
            if parsed["open_thread"] is not None and not isinstance(
                parsed["open_thread"], str
            ):
                return None
            if (
                parsed["objective"] not in OBJECTIVES
                or parsed["tactic"] not in TACTICS
                or not isinstance(parsed["critique"], list)
                or not all(isinstance(item, str) for item in parsed["critique"])
                or isinstance(parsed["confidence"], bool)
                or not isinstance(parsed["confidence"], (int, float))
                or not math.isfinite(float(parsed["confidence"]))
                or not 0 <= float(parsed["confidence"]) <= 1
            ):
                return None
        if parsed is None:
            plain = _text(raw, 2_000)
            if not plain or plain.startswith(("{", "[")):
                return None
            return cls(
                fan_state="unknown",
                state_summary="No structured assessment returned.",
                objective=(
                    "reconnect"
                    if proactive_kind in {"online", "stalled"}
                    else "answer"
                ),
                tactic=(
                    "gentle_check_in"
                    if proactive_kind in {"online", "stalled"}
                    else "direct_answer"
                ),
                open_thread=None,
                draft=plain,
                critique=("legacy plain-text fallback",),
                final_message=plain,
                confidence=0.25,
            )

        objective = _text(parsed.get("objective"), 64).lower()
        if objective not in OBJECTIVES:
            objective = (
                "reconnect"
                if proactive_kind in {"online", "stalled"}
                else "answer"
            )
        tactic = _text(parsed.get("tactic"), 64).lower()
        if tactic not in TACTICS:
            tactic = (
                "gentle_check_in"
                if proactive_kind in {"online", "stalled"}
                else "direct_answer"
            )
        raw_critique = parsed.get("critique")
        if isinstance(raw_critique, dict):
            raw_critique = [
                f"{key}: {value}"
                for key, value in raw_critique.items()
                if value not in (None, "", [], {})
            ]
        if not isinstance(raw_critique, list):
            raw_critique = []
        critique = tuple(
            _text(item, 240)
            for item in raw_critique[:8]
            if _text(item, 240)
        )
        final_value = parsed.get("final_message") or parsed.get("message")
        if not isinstance(final_value, str):
            return None
        final_message = _text(final_value, 2_000)
        if not final_message:
            return None
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        if not math.isfinite(confidence):
            confidence = 0.5
        open_thread = _text(parsed.get("open_thread"), 500) or None
        return cls(
            fan_state=_text(parsed.get("fan_state"), 64) or "unknown",
            state_summary=(
                _text(parsed.get("state_summary"), 1_000)
                or "No state summary returned."
            ),
            objective=objective,
            tactic=tactic,
            open_thread=open_thread,
            draft=_text(parsed.get("draft"), 2_000) or final_message,
            critique=critique,
            final_message=final_message,
            confidence=min(max(confidence, 0.0), 1.0),
        )
