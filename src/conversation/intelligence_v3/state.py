"""Evidence-backed relationship-state reduction with bounded transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from src.conversation.intelligence_v3.contracts import RelationshipSnapshot


STAGE_ORDER = (
    "new",
    "recognition",
    "comfortable",
    "developing_trust",
    "emotionally_open",
    "established",
)
SPECIAL_STAGES = {"cooling", "repair_needed", "boundary_limited"}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
BOUNDARY_RE = re.compile(
    r"\b(stop|don't|do not|not comfortable|too much|leave me alone|no thanks)\b",
    re.IGNORECASE,
)
CORRECTION_RE = re.compile(
    r"\b(no,? i|actually|that's not|you forgot|i told you|not what i said)\b",
    re.IGNORECASE,
)
CALLBACK_RE = re.compile(
    r"\b(tomorrow|later today|next week|this weekend|appointment|interview|"
    r"exam|birthday|trip|surgery)\b",
    re.IGNORECASE,
)
SENSITIVE_CALLBACK_RE = re.compile(
    r"\b(surgery|doctor|hospital|grief|died|funeral|illness)\b",
    re.IGNORECASE,
)
OPENNESS_RE = re.compile(
    r"\b(i feel|i'm scared|i am scared|i miss|i trust|never told|confess|worried|hurt)\b",
    re.IGNORECASE,
)
PLAY_RE = re.compile(r"(?:😂|🤣|😏|😉|\blol\b|\bhaha+\b)", re.IGNORECASE)
LOW_ENERGY_RE = re.compile(r"\b(tired|exhausted|sleepy|drained|quiet|down)\b", re.IGNORECASE)
HIGH_ENERGY_RE = re.compile(r"\b(excited|amazing|omg|can't wait|so happy|hyped)\b", re.IGNORECASE)
UNCERTAINTY_RE = re.compile(r"\b(maybe|not sure|i don't know|i dont know|confused|unsure)\b", re.IGNORECASE)
SEXUAL_INTENSITY_RE = re.compile(
    r"\b(horny|turned on|naked|nude|sex|fuck|cum|cock|pussy|fantasy)\b",
    re.IGNORECASE,
)
FAN_PROMISE_RE = re.compile(r"\b(i(?:'ll| will| promise)|you have my word)\b", re.IGNORECASE)
TOPIC_RE = re.compile(
    r"\b(interview|exam|school|work|job|birthday|trip|appointment|doctor|"
    r"hospital|surgery|family|dog|cat|relationship|weekend)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StateProposal:
    relationship: RelationshipSnapshot
    current_intent: str
    underlying_need: str
    boundary_signal: str | None
    direct_question: str | None
    unresolved_emotional_thread: str | None
    current_emotion: str
    current_energy: str
    openness: float
    sexual_intensity: float
    uncertainty: float
    active_topic: str | None
    fan_promise: str | None
    future_callback: str | None
    recommended_next_act: str
    source_message_id: str
    source_timestamp: datetime


@dataclass(frozen=True)
class StateReduction:
    accepted: bool
    reason: str
    state: dict
    transitions: tuple[dict, ...]


def _bounded(value: object) -> float:
    return round(min(max(float(value or 0.0), 0.0), 1.0), 4)


def infer_deterministic_proposal(
    *,
    message: str,
    source_message_id: str,
    source_timestamp: datetime,
    previous: dict | None = None,
) -> StateProposal:
    """Produce conservative observable signals; never infer from length alone."""
    previous = previous or {}
    text = str(message or "").strip()
    boundary = BOUNDARY_RE.search(text)
    correction = CORRECTION_RE.search(text)
    openness = bool(OPENNESS_RE.search(text))
    playful = bool(PLAY_RE.search(text))
    low_energy = bool(LOW_ENERGY_RE.search(text))
    high_energy = bool(HIGH_ENERGY_RE.search(text))
    uncertain = bool(UNCERTAINTY_RE.search(text))
    sexual = bool(SEXUAL_INTENSITY_RE.search(text))
    topic = TOPIC_RE.search(text)
    callback = CALLBACK_RE.search(text)
    fan_promise = FAN_PROMISE_RE.search(text)
    direct_question = text[:500] if "?" in text else None
    stage = str(previous.get("stage") or previous.get("relationship_stage") or "new")
    if stage not in set(STAGE_ORDER) | SPECIAL_STAGES:
        stage = "new"
    if boundary:
        stage = "boundary_limited"
    elif correction:
        stage = "repair_needed"
    elif openness and stage in {"new", "recognition", "comfortable"}:
        stage = "developing_trust"
    snapshot = RelationshipSnapshot(
        stage=stage,
        trust=_bounded(previous.get("trust", previous.get("trust_estimate", 0.0)) + (0.04 if openness else 0)),
        familiarity=_bounded(previous.get("familiarity", previous.get("familiarity_estimate", 0.0))),
        warmth=_bounded(previous.get("warmth", previous.get("warmth_estimate", 0.0)) + (0.03 if playful else 0)),
        reciprocity=_bounded(previous.get("reciprocity", previous.get("reciprocity_estimate", 0.0))),
        playfulness=_bounded(previous.get("playfulness", previous.get("playfulness_estimate", 0.0)) + (0.06 if playful else 0)),
        emotional_depth=_bounded(previous.get("emotional_depth", 0.0) + (0.08 if openness else 0)),
        fantasy_openness=_bounded(previous.get("fantasy_openness", 0.0)),
        question_fatigue=_bounded(previous.get("question_fatigue", 0.0)),
        pet_name_tolerance=str(previous.get("pet_name_tolerance") or "unknown"),
        momentum="repair" if correction or boundary else str(previous.get("current_momentum") or "steady"),
        intimacy_ceiling="boundary_limited" if boundary else str(previous.get("intimacy_ceiling") or "neutral"),
        evidence=[
            {
                "source_message_id": source_message_id,
                "observation": code,
                "confidence": confidence,
            }
            for code, confidence, present in (
                ("explicit_boundary_language", 1.0, bool(boundary)),
                ("explicit_correction_language", 0.95, bool(correction)),
                ("personal_emotional_disclosure", 0.75, openness),
                ("observable_playful_cue", 0.7, playful),
                ("direct_question_present", 1.0, bool(direct_question)),
            )
            if present
        ],
    )
    return StateProposal(
        relationship=snapshot,
        current_intent=(
            "set_boundary"
            if boundary
            else "correct_context"
            if correction
            else "seek_support"
            if openness
            else "continue_conversation"
        ),
        underlying_need=(
            "respect_and_space"
            if boundary
            else "be_understood"
            if correction
            else "emotional_attunement"
            if openness
            else "connection"
        ),
        boundary_signal=boundary.group(0).lower() if boundary else None,
        direct_question=direct_question,
        unresolved_emotional_thread="personal_disclosure" if openness else None,
        current_emotion=(
            "boundary_assertion"
            if boundary
            else "frustrated_correction"
            if correction
            else "vulnerable"
            if openness
            else "playful"
            if playful
            else "neutral"
        ),
        current_energy=(
            "low" if low_energy else "high" if high_energy else "medium"
        ),
        openness=1.0 if openness else _bounded(previous.get("openness", 0.0)),
        sexual_intensity=(
            0.8
            if sexual
            else _bounded(previous.get("sexual_intensity", 0.0) * 0.8)
        ),
        uncertainty=(
            0.8
            if uncertain
            else _bounded(previous.get("uncertainty", 0.0) * 0.75)
        ),
        active_topic=(
            topic.group(0).lower()
            if topic
            else str(previous.get("active_topic") or "").strip()[:128] or None
        ),
        fan_promise=text[:500] if fan_promise else previous.get("fan_promise"),
        future_callback=(
            callback.group(0).lower()
            if callback
            else previous.get("future_callback")
        ),
        recommended_next_act=(
            "give_space"
            if boundary
            else "repair"
            if correction
            else "support"
            if openness
            else "answer"
            if direct_question
            else "maintain"
        ),
        source_message_id=str(source_message_id)[:128],
        source_timestamp=source_timestamp,
    )


def infer_callback(
    *,
    message: str,
    source_message_id: str,
    source_timestamp: datetime,
) -> dict | None:
    """Capture only explicit future/event anchors; never invent a callback."""
    text = str(message or "").strip()
    match = CALLBACK_RE.search(text)
    if not match:
        return None
    sensitive = bool(SENSITIVE_CALLBACK_RE.search(text))
    return {
        "subject": text[:500],
        "subject_key": re.sub(
            r"[^a-z0-9]+",
            "-",
            match.group(0).lower(),
        ).strip("-"),
        "source_message_id": str(source_message_id)[:128],
        "first_mentioned_at": source_timestamp,
        "emotional_sensitivity": "sensitive" if sensitive else "standard",
        "earliest_safe_reuse_at": source_timestamp
        + timedelta(hours=24 if sensitive else 6),
        "current_relevance": 0.8 if sensitive else 0.65,
        "resolved": False,
    }


class RelationshipStateReducer:
    """Reject stale evidence and prevent weak evidence from causing stage leaps."""

    fields = (
        "relationship_stage",
        "trust_estimate",
        "familiarity_estimate",
        "warmth_estimate",
        "reciprocity_estimate",
        "playfulness_estimate",
        "emotional_depth",
        "fantasy_openness",
        "question_fatigue",
        "pet_name_tolerance",
        "current_momentum",
        "intimacy_ceiling",
        "current_intent",
        "underlying_need",
        "boundary_signal",
        "direct_unanswered_question",
        "unresolved_emotional_thread",
        "current_emotion",
        "current_energy",
        "openness",
        "sexual_intensity",
        "uncertainty",
        "active_topic",
        "creator_promise",
        "fan_promise",
        "future_callback",
        "last_successful_act",
        "recent_failed_acts",
        "recommended_next_act",
    )

    def reduce(self, previous: dict | None, proposal: StateProposal) -> StateReduction:
        previous = dict(previous or {})
        last_timestamp = previous.get("last_source_timestamp")
        if last_timestamp is not None and _aware(proposal.source_timestamp) <= _aware(last_timestamp):
            return StateReduction(False, "stale_source", previous, ())
        if str(previous.get("last_source_message_id") or "") == proposal.source_message_id:
            return StateReduction(False, "duplicate_source", previous, ())
        candidate = self._candidate_state(previous, proposal)
        current_stage = str(previous.get("relationship_stage") or "new")
        candidate["relationship_stage"] = self._bounded_stage(
            current_stage,
            candidate["relationship_stage"],
            proposal,
        )
        version = int(previous.get("version") or 0) + 1
        candidate.update(
            version=version,
            last_source_message_id=proposal.source_message_id,
            last_source_timestamp=proposal.source_timestamp,
        )
        transitions = []
        confidence = max(
            (item.confidence for item in proposal.relationship.evidence),
            default=0.5,
        )
        for field in self.fields:
            old = previous.get(field)
            new = candidate.get(field)
            if old == new:
                continue
            transitions.append(
                {
                    "field_name": field,
                    "previous_value": old,
                    "new_value": new,
                    "confidence": confidence,
                    "source_message_id": proposal.source_message_id,
                    "source_timestamp": proposal.source_timestamp,
                    "evidence_summary": ",".join(
                        item.observation for item in proposal.relationship.evidence
                    )[:240]
                    or "conservative_observable_update",
                    "reason_code": (
                        "explicit_safety_signal"
                        if proposal.boundary_signal
                        else "evidence_backed_update"
                    ),
                    "state_version": version,
                }
            )
        return StateReduction(True, "accepted", candidate, tuple(transitions))

    @staticmethod
    def _candidate_state(previous: dict, proposal: StateProposal) -> dict:
        relationship = proposal.relationship
        return {
            **previous,
            "relationship_stage": relationship.stage,
            "trust_estimate": relationship.trust,
            "familiarity_estimate": relationship.familiarity,
            "warmth_estimate": relationship.warmth,
            "reciprocity_estimate": relationship.reciprocity,
            "playfulness_estimate": relationship.playfulness,
            "emotional_depth": relationship.emotional_depth,
            "fantasy_openness": relationship.fantasy_openness,
            "question_fatigue": relationship.question_fatigue,
            "pet_name_tolerance": relationship.pet_name_tolerance,
            "current_momentum": relationship.momentum,
            "intimacy_ceiling": relationship.intimacy_ceiling,
            "current_intent": proposal.current_intent,
            "underlying_need": proposal.underlying_need,
            "boundary_signal": proposal.boundary_signal,
            "direct_unanswered_question": proposal.direct_question,
            "unresolved_emotional_thread": proposal.unresolved_emotional_thread,
            "current_emotion": proposal.current_emotion,
            "current_energy": proposal.current_energy,
            "openness": proposal.openness,
            "sexual_intensity": proposal.sexual_intensity,
            "uncertainty": proposal.uncertainty,
            "active_topic": proposal.active_topic,
            "creator_promise": previous.get("creator_promise"),
            "fan_promise": proposal.fan_promise,
            "future_callback": proposal.future_callback,
            "last_successful_act": previous.get("last_successful_act"),
            "recent_failed_acts": list(previous.get("recent_failed_acts") or [])[-5:],
            "recommended_next_act": proposal.recommended_next_act,
        }

    @staticmethod
    def _bounded_stage(current: str, proposed: str, proposal: StateProposal) -> str:
        if proposed in SPECIAL_STAGES:
            return proposed
        if current in SPECIAL_STAGES:
            return proposed if proposed in {"new", "recognition", "comfortable"} else current
        try:
            current_index = STAGE_ORDER.index(current)
            proposed_index = STAGE_ORDER.index(proposed)
        except ValueError:
            return "new"
        strongest = max(
            (item.confidence for item in proposal.relationship.evidence),
            default=0.0,
        )
        maximum_step = 1 if strongest < 0.9 else 2
        if proposed_index > current_index + maximum_step:
            return STAGE_ORDER[current_index + maximum_step]
        return proposed
