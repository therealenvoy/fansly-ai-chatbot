"""Durable audit records for conversation-brain decisions."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.conversation.brain import ConversationDecision
from src.persistence.schema import CONVERSATION_DECISIONS, utcnow


@dataclass(frozen=True)
class StoredConversationDecision:
    id: int
    inbound_message_id: int
    creator_id: str
    fan_id: str
    trigger_kind: str
    decision: ConversationDecision
    model: str
    authority: str = "current"
    brain_version: str = "current-v1"
    route: str | None = None
    experiment_id: str | None = None
    variant: str | None = None
    provider_attempts: int = 0
    model_calls: int = 0
    retry_calls: int = 0
    repair_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    estimated_cost: float = 0.0
    fallback_used: bool = False
    fallback_reason: str | None = None
    gate_results: dict | None = None
    safety_rejection_reason: str | None = None


class ConversationDecisionRepository:
    """Store the plan that produced each approved outbound turn."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def save(
        self,
        *,
        inbound_message_id: int,
        creator_id: str,
        fan_id: str,
        trigger_kind: str,
        decision: ConversationDecision,
        model: str,
        execution: dict | None = None,
    ) -> int:
        now = utcnow()
        execution = execution or {}
        values = {
            "inbound_message_id": inbound_message_id,
            "creator_id": creator_id,
            "fan_id": fan_id,
            "trigger_kind": trigger_kind,
            "fan_state": decision.fan_state,
            "state_summary": decision.state_summary,
            "objective": decision.objective,
            "tactic": decision.tactic,
            "open_thread": decision.open_thread,
            "draft": decision.draft,
            "critique": list(decision.critique),
            "final_message": decision.final_message,
            "confidence": decision.confidence,
            "model": model,
            "authority": str(execution.get("authority") or "current"),
            "brain_version": str(execution.get("brain_version") or "current-v1"),
            "route": execution.get("route"),
            "experiment_id": execution.get("experiment_id"),
            "variant": execution.get("variant"),
            "provider_attempts": int(execution.get("provider_attempts") or 0),
            "model_calls": int(execution.get("model_calls") or 0),
            "retry_calls": int(execution.get("retry_calls") or 0),
            "repair_calls": int(execution.get("repair_calls") or 0),
            "prompt_tokens": int(execution.get("prompt_tokens") or 0),
            "completion_tokens": int(execution.get("completion_tokens") or 0),
            "total_tokens": int(execution.get("total_tokens") or 0),
            "latency_ms": int(execution.get("latency_ms") or 0),
            "estimated_cost": float(execution.get("estimated_cost") or 0.0),
            "fallback_used": bool(execution.get("fallback_used")),
            "fallback_reason": execution.get("fallback_reason"),
            "gate_results": execution.get("gate_results") or {},
            "safety_rejection_reason": execution.get("safety_rejection_reason"),
            "created_at": now,
            "updated_at": now,
        }
        statement = self._insert().values(**values)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=["inbound_message_id"],
            set_={
                "fan_state": excluded.fan_state,
                "state_summary": excluded.state_summary,
                "objective": excluded.objective,
                "tactic": excluded.tactic,
                "open_thread": excluded.open_thread,
                "draft": excluded.draft,
                "critique": excluded.critique,
                "final_message": excluded.final_message,
                "confidence": excluded.confidence,
                "model": excluded.model,
                "authority": excluded.authority,
                "brain_version": excluded.brain_version,
                "route": excluded.route,
                "experiment_id": excluded.experiment_id,
                "variant": excluded.variant,
                "provider_attempts": excluded.provider_attempts,
                "model_calls": excluded.model_calls,
                "retry_calls": excluded.retry_calls,
                "repair_calls": excluded.repair_calls,
                "prompt_tokens": excluded.prompt_tokens,
                "completion_tokens": excluded.completion_tokens,
                "total_tokens": excluded.total_tokens,
                "latency_ms": excluded.latency_ms,
                "estimated_cost": excluded.estimated_cost,
                "fallback_used": excluded.fallback_used,
                "fallback_reason": excluded.fallback_reason,
                "gate_results": excluded.gate_results,
                "safety_rejection_reason": excluded.safety_rejection_reason,
                "updated_at": now,
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)
            decision_id = connection.execute(
                select(CONVERSATION_DECISIONS.c.id).where(
                    CONVERSATION_DECISIONS.c.inbound_message_id == inbound_message_id
                )
            ).scalar_one()
        return int(decision_id)

    def get(
        self,
        inbound_message_id: int,
        *,
        creator_id: str,
    ) -> StoredConversationDecision | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(CONVERSATION_DECISIONS).where(
                    and_(
                        CONVERSATION_DECISIONS.c.inbound_message_id
                        == inbound_message_id,
                        CONVERSATION_DECISIONS.c.creator_id == creator_id,
                    )
                )
            ).mappings().first()
        if row is None:
            return None
        return StoredConversationDecision(
            id=int(row["id"]),
            inbound_message_id=int(row["inbound_message_id"]),
            creator_id=str(row["creator_id"]),
            fan_id=str(row["fan_id"]),
            trigger_kind=str(row["trigger_kind"]),
            decision=ConversationDecision(
                fan_state=str(row["fan_state"]),
                state_summary=str(row["state_summary"]),
                objective=str(row["objective"]),
                tactic=str(row["tactic"]),
                open_thread=row["open_thread"],
                draft=str(row["draft"]),
                critique=tuple(row["critique"] or ()),
                final_message=str(row["final_message"]),
                confidence=float(row["confidence"]),
            ),
            model=str(row["model"]),
            authority=str(row["authority"] or "current"),
            brain_version=str(row["brain_version"] or "current-v1"),
            route=row["route"],
            experiment_id=row["experiment_id"],
            variant=row["variant"],
            provider_attempts=int(row["provider_attempts"] or 0),
            model_calls=int(row["model_calls"] or 0),
            retry_calls=int(row["retry_calls"] or 0),
            repair_calls=int(row["repair_calls"] or 0),
            prompt_tokens=int(row["prompt_tokens"] or 0),
            completion_tokens=int(row["completion_tokens"] or 0),
            total_tokens=int(row["total_tokens"] or 0),
            latency_ms=int(row["latency_ms"] or 0),
            estimated_cost=float(row["estimated_cost"] or 0),
            fallback_used=bool(row["fallback_used"]),
            fallback_reason=row["fallback_reason"],
            gate_results=dict(row["gate_results"] or {}),
            safety_rejection_reason=row["safety_rejection_reason"],
        )

    def latest_for_fan(
        self,
        *,
        creator_id: str,
        fan_id: str,
        limit: int = 5,
    ) -> list[StoredConversationDecision]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(CONVERSATION_DECISIONS)
                .where(
                    and_(
                        CONVERSATION_DECISIONS.c.creator_id == creator_id,
                        CONVERSATION_DECISIONS.c.fan_id == fan_id,
                    )
                )
                .order_by(
                    CONVERSATION_DECISIONS.c.created_at.desc(),
                    CONVERSATION_DECISIONS.c.id.desc(),
                )
                .limit(max(1, min(int(limit), 20)))
            ).mappings().all()
        return [
            StoredConversationDecision(
                id=int(row["id"]),
                inbound_message_id=int(row["inbound_message_id"]),
                creator_id=str(row["creator_id"]),
                fan_id=str(row["fan_id"]),
                trigger_kind=str(row["trigger_kind"]),
                decision=ConversationDecision(
                    fan_state=str(row["fan_state"]),
                    state_summary=str(row["state_summary"]),
                    objective=str(row["objective"]),
                    tactic=str(row["tactic"]),
                    open_thread=row["open_thread"],
                    draft=str(row["draft"]),
                    critique=tuple(row["critique"] or ()),
                    final_message=str(row["final_message"]),
                    confidence=float(row["confidence"]),
                ),
                model=str(row["model"]),
            )
            for row in rows
        ]

    def latest_execution_attempts(
        self,
        *,
        creator_id: str,
        limit: int = 100,
    ) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    CONVERSATION_DECISIONS.c.authority,
                    CONVERSATION_DECISIONS.c.fallback_used,
                    CONVERSATION_DECISIONS.c.fallback_reason,
                    CONVERSATION_DECISIONS.c.route,
                    CONVERSATION_DECISIONS.c.latency_ms,
                    CONVERSATION_DECISIONS.c.gate_results,
                )
                .where(
                    and_(
                        CONVERSATION_DECISIONS.c.creator_id == creator_id,
                        (
                            (CONVERSATION_DECISIONS.c.authority == "advanced")
                            | (CONVERSATION_DECISIONS.c.fallback_used.is_(True))
                        ),
                    )
                )
                .order_by(CONVERSATION_DECISIONS.c.created_at.desc())
                .limit(max(1, min(int(limit), 500)))
            ).mappings().all()
        return [dict(row) for row in rows]

    def _insert(self):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(CONVERSATION_DECISIONS)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(CONVERSATION_DECISIONS)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
