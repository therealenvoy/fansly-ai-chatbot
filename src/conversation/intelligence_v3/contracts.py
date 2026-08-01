"""Strict public contracts for evidence-backed planning without private reasoning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RelationshipStage = Literal[
    "new",
    "recognition",
    "comfortable",
    "developing_trust",
    "emotionally_open",
    "established",
    "cooling",
    "repair_needed",
    "boundary_limited",
]
PrimaryAct = Literal[
    "answer",
    "validate",
    "support",
    "play",
    "deepen",
    "learn",
    "tease",
    "repair",
    "reassure",
    "maintain",
    "reconnect",
    "transition",
    "give_space",
]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceObservation(StrictContract):
    source_message_id: str = Field(min_length=1, max_length=128)
    observation: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0.0, le=1.0)


class RelationshipSnapshot(StrictContract):
    stage: RelationshipStage = "new"
    trust: float = Field(default=0.0, ge=0.0, le=1.0)
    familiarity: float = Field(default=0.0, ge=0.0, le=1.0)
    warmth: float = Field(default=0.0, ge=0.0, le=1.0)
    reciprocity: float = Field(default=0.0, ge=0.0, le=1.0)
    playfulness: float = Field(default=0.0, ge=0.0, le=1.0)
    emotional_depth: float = Field(default=0.0, ge=0.0, le=1.0)
    fantasy_openness: float = Field(default=0.0, ge=0.0, le=1.0)
    question_fatigue: float = Field(default=0.0, ge=0.0, le=1.0)
    pet_name_tolerance: Literal["unknown", "low", "medium", "high"] = "unknown"
    momentum: Literal["low", "steady", "high", "cooling", "repair"] = "steady"
    intimacy_ceiling: Literal[
        "neutral",
        "warm",
        "flirty",
        "explicit_consensual",
        "boundary_limited",
    ] = "neutral"
    evidence: list[EvidenceObservation] = Field(default_factory=list, max_length=20)


class TurnUnderstanding(StrictContract):
    emotion: str = Field(min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=96)
    active_thread: str = Field(default="", max_length=240)
    underlying_need: str = Field(default="", max_length=120)
    direct_question: str | None = Field(default=None, max_length=500)
    evidence: list[EvidenceObservation] = Field(min_length=1, max_length=12)


class StrategyDecision(StrictContract):
    primary_act: PrimaryAct
    secondary_act: PrimaryAct | None = None
    must_reference: list[str] = Field(default_factory=list, max_length=8)
    must_avoid: list[str] = Field(default_factory=list, max_length=12)
    should_ask_question: bool = False
    desired_effect: str = Field(min_length=1, max_length=160)
    used_callback_ids: list[int] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def distinct_acts(self):
        if self.secondary_act == self.primary_act:
            raise ValueError("secondary act must differ from primary act")
        return self


class DeliveryDecision(StrictContract):
    bubble_count: int = Field(default=1, ge=1, le=3)
    energy: Literal["low", "medium", "high", "serious"] = "medium"
    length: Literal["minimal", "short", "medium"] = "short"
    emoji_budget: int = Field(default=0, ge=0, le=3)


class CandidateDraft(StrictContract):
    candidate_id: str = Field(min_length=1, max_length=64)
    act: PrimaryAct
    structure: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    addresses_direct_question: bool = False


class CandidateAssessment(StrictContract):
    candidate_id: str = Field(min_length=1, max_length=64)
    scores: dict[str, float]
    rejection_codes: list[str] = Field(default_factory=list, max_length=20)
    approved: bool

    @field_validator("scores")
    @classmethod
    def bounded_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("candidate scores are required")
        normalized = {}
        for key, score in value.items():
            number = float(score)
            if number < 0 or number > 10:
                raise ValueError("candidate scores must be between 0 and 10")
            normalized[str(key)[:64]] = number
        return normalized


class HighEQPlan(StrictContract):
    understanding: TurnUnderstanding
    relationship: RelationshipSnapshot
    strategy: StrategyDecision
    delivery: DeliveryDecision
    candidates: list[CandidateDraft] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def candidates_use_distinct_moves(self):
        moves = {(item.act, item.structure) for item in self.candidates}
        if len(moves) != len(self.candidates):
            raise ValueError("candidates must use distinct acts or structures")
        return self
