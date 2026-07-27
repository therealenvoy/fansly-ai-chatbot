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
    inbound_message_id: int
    creator_id: str
    fan_id: str
    trigger_kind: str
    decision: ConversationDecision
    model: str


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
    ) -> None:
        now = utcnow()
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
                "updated_at": now,
            },
        )
        with self.engine.begin() as connection:
            connection.execute(statement)

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

    def _insert(self):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(CONVERSATION_DECISIONS)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(CONVERSATION_DECISIONS)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
