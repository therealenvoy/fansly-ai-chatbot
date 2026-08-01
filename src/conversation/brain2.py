"""Pure routing, settings, and deterministic gates for Brain 2.0."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Mapping

from src.conversation.diversity import diversity_reason_codes


def _integer(value, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, low), high)


def _boolean(value, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _decimal(value, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, low), high)


@dataclass(frozen=True)
class BrainRuntimeSettings:
    mode: str = "current"
    version: str = "brain2-v1"
    shadow_sample_percent: int = 0
    strategic_complexity_threshold: int = 3
    max_strategic_calls_per_hour: int = 25
    max_strategic_calls_per_day: int = 100
    max_model_calls_per_turn: int = 4
    max_output_tokens: int = 800
    json_repair_attempts: int = 1
    outcome_window_hours: int = 24
    allow_advanced_send: bool = False
    live_percent: int = 0
    max_live_percent: int = 0
    auto_rollback: bool = True
    live_timeout_seconds: float = 8.0
    max_daily_cost: float = 0.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]):
        mode = str(values.get("BRAIN_MODE", "current")).strip().lower()
        if mode not in {"current", "shadow", "advanced"}:
            mode = "current"
        return cls(
            mode=mode,
            version=str(values.get("BRAIN_VERSION", "brain2-v1"))[:64],
            shadow_sample_percent=_integer(
                values.get("BRAIN_SHADOW_SAMPLE_PERCENT"), 0, 0, 100
            ),
            strategic_complexity_threshold=_integer(
                values.get("BRAIN_STRATEGIC_COMPLEXITY_THRESHOLD"), 3, 1, 10
            ),
            max_strategic_calls_per_hour=_integer(
                values.get("BRAIN_MAX_STRATEGIC_CALLS_PER_HOUR"), 25, 0, 10_000
            ),
            max_strategic_calls_per_day=_integer(
                values.get("BRAIN_MAX_STRATEGIC_CALLS_PER_DAY"), 100, 0, 100_000
            ),
            max_model_calls_per_turn=_integer(
                values.get("BRAIN_MAX_MODEL_CALLS_PER_TURN"), 4, 1, 4
            ),
            max_output_tokens=_integer(
                values.get("BRAIN_MAX_OUTPUT_TOKENS"), 800, 256, 4_096
            ),
            json_repair_attempts=_integer(
                values.get("BRAIN_JSON_REPAIR_ATTEMPTS"), 1, 0, 1
            ),
            outcome_window_hours=_integer(
                values.get("BRAIN_OUTCOME_WINDOW_HOURS"), 24, 1, 168
            ),
            allow_advanced_send=_boolean(
                values.get("BRAIN_ALLOW_ADVANCED_SEND"), False
            ),
            live_percent=_integer(
                values.get("BRAIN_LIVE_PERCENT"), 0, 0, 100
            ),
            max_live_percent=_integer(
                values.get("BRAIN_MAX_LIVE_PERCENT"), 0, 0, 100
            ),
            auto_rollback=_boolean(
                values.get("BRAIN_AUTO_ROLLBACK"), True
            ),
            live_timeout_seconds=_decimal(
                values.get("BRAIN_LIVE_TIMEOUT_SECONDS"), 8.0, 1.0, 30.0
            ),
            max_daily_cost=_decimal(
                values.get("BRAIN_MAX_DAILY_COST"), 0.0, 0.0, 100_000.0
            ),
        )


@dataclass(frozen=True)
class BrainRoute:
    path: str
    reasons: tuple[str, ...]
    complexity_score: int
    risk_flags: tuple[str, ...]
    estimated_call_budget: int
    router_version: str = "router-v1"


class BrainRouter:
    _VULNERABLE = re.compile(
        r"\b(alone|anxious|depressed|hurt|scared|upset|crying|"
        r"overwhelmed|don't know what to do|do not know what to do)\b",
        re.IGNORECASE,
    )
    _BOUNDARY = re.compile(
        r"\b(stop|don't|do not|uncomfortable|boundary|leave me alone)\b",
        re.IGNORECASE,
    )

    def __init__(self, threshold: int = 3):
        self.threshold = threshold

    def route(
        self,
        *,
        fan_message: str,
        trigger_kind: str,
        history: str,
        has_memory_conflict: bool,
        failed_tactic_count: int,
        context_confidence: float,
    ) -> BrainRoute:
        reasons: list[str] = []
        risks: list[str] = []
        score = 0
        text = str(fan_message or "")
        if trigger_kind == "stalled":
            reasons.append("stalled_reopening")
            score += 3
        if self._VULNERABLE.search(text):
            reasons.append("vulnerability")
            risks.append("emotional")
            score += 4
        if self._BOUNDARY.search(text):
            reasons.append("boundary_sensitive")
            risks.append("boundary")
            score += 5
        if has_memory_conflict:
            reasons.append("memory_conflict")
            score += 3
        if failed_tactic_count >= 2:
            reasons.append("repeated_failed_tactic")
            score += 2
        if context_confidence < 0.55:
            reasons.append("low_context_confidence")
            score += 2
        if len(text) > 500:
            reasons.append("long_message")
            score += 2
        path = "strategic" if score >= self.threshold else "fast"
        return BrainRoute(
            path=path,
            reasons=tuple(reasons or ("routine",)),
            complexity_score=score,
            risk_flags=tuple(risks),
            estimated_call_budget=3 if path == "strategic" else 1,
        )


@dataclass(frozen=True)
class GateResult:
    approved: bool
    reason_codes: tuple[str, ...]


class ConversationQualityGate:
    _SALES = re.compile(
        r"(?:\bppv\b|\bunlock\b|\btip(?:ping)?\b|\$\s*\d+|"
        r"\b(?:buy|purchase|pay)\b|locked content)",
        re.IGNORECASE,
    )
    _TRACKING = re.compile(
        r"(?:saw|noticed|watching).{0,24}\b(?:online|active)\b|"
        r"\b(?:ghost(?:ed|ing)?|inactive|monitoring|tracking)\b",
        re.IGNORECASE,
    )
    _MEDIA_PROMISE = re.compile(
        r"\b(?:made|recorded|filmed|send|sending).{0,24}"
        r"(?:video|photo|pic|content).{0,24}(?:for you|to you)\b",
        re.IGNORECASE,
    )
    _INJECTION_ECHO = re.compile(
        r"(?:ignore|disregard).{0,32}(?:instructions|system|developer)|"
        r"(?:system|developer)\s+(?:prompt|message)|jailbreak",
        re.IGNORECASE,
    )
    _REAL_WORLD_ACTIVITY = re.compile(
        r"\bi\s+(?:just\s+)?(?:got home|woke up|finished work|"
        r"went out|came back|am at (?:the )?(?:gym|store|office)|"
        r"recorded|filmed)\b",
        re.IGNORECASE,
    )

    def evaluate(
        self,
        text: str,
        *,
        recent_creator_messages: list[str],
        question_streak: int = 0,
        pet_name_streak: int = 0,
        pet_names: tuple[str, ...] = ("babe", "baby", "hun", "honey"),
        hard_boundaries: list[str] | tuple[str, ...] = (),
        max_length: int = 500,
    ) -> GateResult:
        normalized = unicodedata.normalize("NFKC", str(text or "")).strip()
        codes: list[str] = []
        if not normalized:
            codes.append("empty_response")
        if len(normalized) > max_length:
            codes.append("length_limit")
        if self._SALES.search(normalized):
            codes.append("sales_or_ppv")
        if self._TRACKING.search(normalized):
            codes.append("online_tracking")
        if self._MEDIA_PROMISE.search(normalized):
            codes.append("media_promise")
        if self._INJECTION_ECHO.search(normalized):
            codes.append("prompt_injection_echo")
        if self._REAL_WORLD_ACTIVITY.search(normalized):
            codes.append("invented_real_world_activity")
        boundary_text = " ".join(
            str(boundary).casefold() for boundary in hard_boundaries
        )
        if (
            "pet name" in boundary_text
            and any(
                re.search(
                    rf"\b{re.escape(name.casefold())}\b",
                    normalized.casefold(),
                )
                for name in pet_names
            )
        ) or (
            any(marker in boundary_text for marker in ("no question", "don't ask", "do not ask"))
            and "?" in normalized
        ) or (
            any(marker in boundary_text for marker in ("no meetup", "no meet up", "no meeting"))
            and re.search(r"\b(?:meet|meetup|meet up)\b", normalized, re.IGNORECASE)
        ):
            codes.append("hard_boundary_conflict")
        if question_streak >= 2 and "?" in normalized:
            codes.append("question_streak")
        lower = normalized.casefold()
        if pet_name_streak >= 2 and any(
            re.search(rf"\b{re.escape(name.casefold())}\b", lower)
            for name in pet_names
        ):
            codes.append("pet_name_streak")
        for recent in recent_creator_messages[-5:]:
            candidate = unicodedata.normalize("NFKC", str(recent)).strip()
            if (
                candidate
                and SequenceMatcher(
                    None,
                    lower,
                    candidate.casefold(),
                ).ratio()
                >= 0.88
            ):
                codes.append("excessive_similarity")
                break
        codes.extend(
            diversity_reason_codes(normalized, recent_creator_messages)
        )
        return GateResult(not codes, tuple(dict.fromkeys(codes)))
