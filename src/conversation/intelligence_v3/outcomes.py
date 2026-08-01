"""Transparent outcome scoring and inert multi-bubble planning."""

from __future__ import annotations

from dataclasses import dataclass
import re


CORRECTION_RE = re.compile(r"\b(no|actually|not what|you forgot|i told you)\b", re.I)
BOUNDARY_RE = re.compile(r"\b(stop|don't|do not|not comfortable|too much)\b", re.I)
BOT_RE = re.compile(r"\b(bot|ai|robot|copy.?paste|scripted)\b", re.I)
DISCLOSURE_RE = re.compile(r"\b(i feel|i've never|i have never|i'm scared|i worry|my dream|my fantasy)\b", re.I)


def semantic_substance(text: object) -> float:
    words = re.findall(r"[a-z0-9']+", str(text or "").lower())
    if not words:
        return 0.0
    unique_ratio = len(set(words)) / len(words)
    return round(min(1.0, (len(words) / 30.0) * 0.5 + unique_ratio * 0.5), 4)


def observe_reply(text: object) -> dict:
    value = str(text or "").strip()
    correction = bool(CORRECTION_RE.search(value))
    boundary = bool(BOUNDARY_RE.search(value))
    bot_suspicion = bool(BOT_RE.search(value))
    disclosure = bool(DISCLOSURE_RE.search(value))
    emotional_shift = (
        -0.7
        if boundary or bot_suspicion
        else -0.35
        if correction
        else 0.45
        if disclosure
        else 0.1
        if value
        else 0.0
    )
    return {
        "reply_length": len(value),
        "semantic_substance": semantic_substance(value),
        "emotional_shift": emotional_shift,
        "disclosure_depth": 0.8 if disclosure else 0.2 if value else 0.0,
        "correction_signal": correction,
        "boundary_signal": boundary,
        "bot_suspicion": bot_suspicion,
    }


def composite_quality(outcome: dict) -> float:
    positive = (
        0.25 * float(bool(outcome.get("fan_replied")))
        + 0.15 * float(bool(outcome.get("meaningful_reply")))
        + 0.15 * float(bool(outcome.get("continued_three_turns")))
        + 0.1 * float(bool(outcome.get("returned_within_24h")))
        + 0.15 * float(outcome.get("semantic_substance") or 0.0)
        + 0.1 * float(outcome.get("disclosure_depth") or 0.0)
        + 0.1 * max(-1.0, min(float(outcome.get("emotional_shift") or 0.0), 1.0))
    )
    negative = (
        0.35 * float(bool(outcome.get("negative_signal")))
        + 0.4 * float(bool(outcome.get("boundary_signal")))
        + 0.4 * float(bool(outcome.get("bot_suspicion")))
        + 0.25 * float(bool(outcome.get("correction_signal")))
        + 0.2 * float(bool(outcome.get("manual_creator_takeover")))
    )
    return round(max(-1.0, min(1.0, positive - negative)), 4)


@dataclass(frozen=True)
class BubblePlan:
    bubble_count: int
    boundaries: tuple[int, ...]
    shadow_only: bool = True


def plan_bubbles(text: str, *, requested: int, mode: str) -> BubblePlan:
    """Return only inert boundaries; never split or enqueue live messages."""
    if mode not in {"shadow", "live"} or requested <= 1:
        return BubblePlan(1, (), True)
    maximum = min(max(int(requested), 1), 3)
    candidates = [match.end() for match in re.finditer(r"[.!?…]+\s+", text)]
    boundaries = tuple(candidates[: maximum - 1])
    return BubblePlan(1 + len(boundaries), boundaries, True)
