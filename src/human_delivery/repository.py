"""Durable repositories for document governance and shadow response plans."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from sqlalchemy import Engine, and_, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.human_delivery.contracts import HumanDeliveryDecision
from src.human_delivery.documents import DOCUMENT_TYPES, DocumentLinter
from src.human_delivery.schema import (
    CONVERSATION_DOCUMENT_EVENTS,
    CONVERSATION_DOCUMENTS,
    CONVERSATION_EXAMPLES,
    FAN_TURN_INBOUND_LINKS,
    FAN_TURNS,
    HUMAN_RESPONSE_BUBBLES,
    HUMAN_RESPONSE_PLANS,
)
from src.persistence.schema import INBOUND_MESSAGES, utcnow


class DocumentRepository:
    """Version prompt documents without altering legacy live settings."""

    def __init__(self, engine: Engine, *, creator_id: str):
        self.engine = engine
        self.creator_id = creator_id
        self.linter = DocumentLinter()

    def list_documents(self) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(CONVERSATION_DOCUMENTS)
                .where(
                    CONVERSATION_DOCUMENTS.c.creator_id
                    == self.creator_id
                )
                .order_by(
                    CONVERSATION_DOCUMENTS.c.document_type,
                    CONVERSATION_DOCUMENTS.c.revision.desc(),
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def active_documents(self) -> dict[str, str]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(
                    CONVERSATION_DOCUMENTS.c.document_type,
                    CONVERSATION_DOCUMENTS.c.content,
                ).where(
                    and_(
                        CONVERSATION_DOCUMENTS.c.creator_id
                        == self.creator_id,
                        CONVERSATION_DOCUMENTS.c.status == "active",
                    )
                )
            ).all()
        return {str(kind): str(content) for kind, content in rows}

    def create_revision(
        self,
        *,
        document_type: str,
        content: str,
        status: str = "draft",
        actor: str = "operator",
        source: str = "crm",
    ) -> dict:
        document_type = str(document_type).strip().lower()
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("unsupported conversation document type")
        normalized = str(content or "").strip()
        if not normalized:
            raise ValueError("conversation document content is required")
        if len(normalized) > 100_000:
            raise ValueError(
                "conversation documents must be 100,000 characters or fewer"
            )
        if status not in {"draft", "active"}:
            raise ValueError("document status must be draft or active")
        now = utcnow()
        with self.engine.begin() as connection:
            revision = int(
                connection.execute(
                    select(
                        func.coalesce(
                            func.max(
                                CONVERSATION_DOCUMENTS.c.revision
                            ),
                            0,
                        )
                    ).where(
                        and_(
                            CONVERSATION_DOCUMENTS.c.creator_id
                            == self.creator_id,
                            CONVERSATION_DOCUMENTS.c.document_type
                            == document_type,
                        )
                    )
                ).scalar_one()
            ) + 1
            active = self._active_map(connection)
            candidate = {**active, document_type: normalized}
            findings = DocumentLinter.serialize(
                self.linter.lint(candidate)
            )
            if status == "active":
                connection.execute(
                    update(CONVERSATION_DOCUMENTS)
                    .where(
                        and_(
                            CONVERSATION_DOCUMENTS.c.creator_id
                            == self.creator_id,
                            CONVERSATION_DOCUMENTS.c.document_type
                            == document_type,
                            CONVERSATION_DOCUMENTS.c.status == "active",
                        )
                    )
                    .values(status="archived", updated_at=now)
                )
            result = connection.execute(
                insert(CONVERSATION_DOCUMENTS).values(
                    creator_id=self.creator_id,
                    document_type=document_type,
                    revision=revision,
                    status=status,
                    content=normalized,
                    character_count=len(normalized),
                    conflict_findings=findings,
                    source=str(source)[:64],
                    created_by=str(actor)[:64],
                    activated_at=now if status == "active" else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            document_id = int(result.inserted_primary_key[0])
            connection.execute(
                insert(CONVERSATION_DOCUMENT_EVENTS).values(
                    document_id=document_id,
                    creator_id=self.creator_id,
                    event_type="created",
                    actor=str(actor)[:64],
                    details={
                        "status": status,
                        "revision": revision,
                        "source": str(source)[:64],
                    },
                    created_at=now,
                )
            )
            row = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    CONVERSATION_DOCUMENTS.c.id == document_id
                )
            ).mappings().one()
        return dict(row)

    def activate(
        self,
        document_id: int,
        *,
        actor: str = "operator",
        conversation_only: bool = True,
    ) -> dict:
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(CONVERSATION_DOCUMENTS)
                .where(
                    and_(
                        CONVERSATION_DOCUMENTS.c.id == int(document_id),
                        CONVERSATION_DOCUMENTS.c.creator_id
                        == self.creator_id,
                    )
                )
                .with_for_update()
            ).mappings().first()
            if row is None:
                raise ValueError("conversation document was not found")
            if conversation_only and row["document_type"] == "sales_playbook":
                raise ValueError(
                    "Sales Playbook cannot be active in conversation-only mode"
                )
            connection.execute(
                update(CONVERSATION_DOCUMENTS)
                .where(
                    and_(
                        CONVERSATION_DOCUMENTS.c.creator_id
                        == self.creator_id,
                        CONVERSATION_DOCUMENTS.c.document_type
                        == row["document_type"],
                        CONVERSATION_DOCUMENTS.c.status == "active",
                    )
                )
                .values(status="archived", updated_at=now)
            )
            connection.execute(
                update(CONVERSATION_DOCUMENTS)
                .where(CONVERSATION_DOCUMENTS.c.id == int(document_id))
                .values(
                    status="active",
                    activated_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(CONVERSATION_DOCUMENT_EVENTS).values(
                    document_id=int(document_id),
                    creator_id=self.creator_id,
                    event_type="activated",
                    actor=str(actor)[:64],
                    details={"previous_status": row["status"]},
                    created_at=now,
                )
            )
            activated = connection.execute(
                select(CONVERSATION_DOCUMENTS).where(
                    CONVERSATION_DOCUMENTS.c.id == int(document_id)
                )
            ).mappings().one()
        return dict(activated)

    def bootstrap(
        self,
        *,
        creator_persona: str,
        brand_bible: str,
        conversation_guide: str,
        suggested_guide: str,
    ) -> dict:
        existing = self.list_documents()
        if existing:
            return {"created": 0, "preserved": True}
        created = 0
        originals = {
            "creator_persona": creator_persona,
            "brand_bible": brand_bible,
            "conversation_guide": conversation_guide,
        }
        for document_type, content in originals.items():
            if str(content or "").strip():
                self.create_revision(
                    document_type=document_type,
                    content=content,
                    status="active",
                    actor="migration",
                    source="legacy_snapshot",
                )
                created += 1
        self.create_revision(
            document_type="conversation_guide",
            content=suggested_guide,
            status="draft",
            actor="system",
            source="human_delivery_v1_suggestion",
        )
        created += 1
        self.create_revision(
            document_type="sales_playbook",
            content=(
                "# Inactive Sales/PPV Playbook\n\n"
                "No sales instructions have been migrated automatically. "
                "This document is excluded from conversation-only prompts."
            ),
            status="draft",
            actor="system",
            source="human_delivery_v1_placeholder",
        )
        created += 1
        return {"created": created, "preserved": True}

    def examples(self, *, status: str = "active", limit: int = 20) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(CONVERSATION_EXAMPLES)
                .where(
                    and_(
                        CONVERSATION_EXAMPLES.c.creator_id
                        == self.creator_id,
                        CONVERSATION_EXAMPLES.c.status == status,
                    )
                )
                .order_by(CONVERSATION_EXAMPLES.c.id.desc())
                .limit(max(1, min(int(limit), 100)))
            ).mappings().all()
        return [dict(row) for row in rows]

    def _active_map(self, connection) -> dict[str, str]:
        rows = connection.execute(
            select(
                CONVERSATION_DOCUMENTS.c.document_type,
                CONVERSATION_DOCUMENTS.c.content,
            ).where(
                and_(
                    CONVERSATION_DOCUMENTS.c.creator_id == self.creator_id,
                    CONVERSATION_DOCUMENTS.c.status == "active",
                )
            )
        ).all()
        return {str(kind): str(content) for kind, content in rows}


class FanTurnRepository:
    """Group webhook-fed inbound rows without provider reads."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def add_inbound(
        self,
        inbound_message_id: int,
        *,
        debounce_seconds: int = 4,
        max_window_seconds: int = 12,
        max_messages: int = 8,
    ) -> dict:
        debounce = min(max(int(debounce_seconds), 1), 15)
        max_window = min(max(int(max_window_seconds), debounce), 30)
        maximum = min(max(int(max_messages), 1), 20)
        now = utcnow()
        with self.engine.begin() as connection:
            inbound = connection.execute(
                select(INBOUND_MESSAGES)
                .where(INBOUND_MESSAGES.c.id == int(inbound_message_id))
                .with_for_update()
            ).mappings().first()
            if inbound is None:
                raise ValueError("inbound message was not found")
            existing_link = connection.execute(
                select(FAN_TURN_INBOUND_LINKS.c.turn_id).where(
                    FAN_TURN_INBOUND_LINKS.c.inbound_message_id
                    == int(inbound_message_id)
                )
            ).scalar_one_or_none()
            if existing_link is not None:
                return self._turn(connection, int(existing_link))
            candidate = connection.execute(
                select(FAN_TURNS)
                .where(
                    and_(
                        FAN_TURNS.c.creator_id == inbound["creator_id"],
                        FAN_TURNS.c.fan_id == inbound["fan_id"],
                        FAN_TURNS.c.chat_id == inbound["chat_id"],
                        FAN_TURNS.c.status == "collecting",
                        FAN_TURNS.c.started_at
                        <= inbound["provider_created_at"],
                        FAN_TURNS.c.closes_at
                        >= inbound["provider_created_at"],
                    )
                )
                .order_by(FAN_TURNS.c.last_message_at.desc())
                .limit(1)
                .with_for_update()
            ).mappings().first()
            count = 0
            if candidate is not None:
                count = int(
                    connection.execute(
                        select(func.count())
                        .select_from(FAN_TURN_INBOUND_LINKS)
                        .where(
                            FAN_TURN_INBOUND_LINKS.c.turn_id
                            == candidate["id"]
                        )
                    ).scalar_one()
                )
            if candidate is None or count >= maximum:
                started = inbound["provider_created_at"]
                turn_key = hashlib.sha256(
                    (
                        f"{inbound['creator_id']}:{inbound['fan_id']}:"
                        f"{inbound['chat_id']}:{inbound['platform_message_id']}"
                    ).encode("utf-8")
                ).hexdigest()[:40]
                result = connection.execute(
                    insert(FAN_TURNS).values(
                        creator_id=inbound["creator_id"],
                        fan_id=inbound["fan_id"],
                        chat_id=inbound["chat_id"],
                        turn_key=turn_key,
                        status="collecting",
                        quiet_until=started + timedelta(seconds=debounce),
                        closes_at=started + timedelta(seconds=max_window),
                        started_at=started,
                        last_message_at=started,
                        created_at=now,
                        updated_at=now,
                    )
                )
                turn_id = int(result.inserted_primary_key[0])
                position = 1
            else:
                turn_id = int(candidate["id"])
                position = count + 1
                latest = max(
                    candidate["last_message_at"],
                    inbound["provider_created_at"],
                )
                quiet_until = min(
                    candidate["closes_at"],
                    latest + timedelta(seconds=debounce),
                )
                connection.execute(
                    update(FAN_TURNS)
                    .where(FAN_TURNS.c.id == turn_id)
                    .values(
                        quiet_until=quiet_until,
                        last_message_at=latest,
                        updated_at=now,
                    )
                )
            connection.execute(
                insert(FAN_TURN_INBOUND_LINKS).values(
                    turn_id=turn_id,
                    inbound_message_id=int(inbound_message_id),
                    position=position,
                    linked_at=now,
                )
            )
            self._resequence(connection, turn_id)
            return self._turn(connection, turn_id)

    def close_ready(
        self,
        *,
        creator_id: str,
        now: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        effective_now = now or utcnow()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(FAN_TURNS)
                .where(
                    and_(
                        FAN_TURNS.c.creator_id == creator_id,
                        FAN_TURNS.c.status == "collecting",
                        FAN_TURNS.c.quiet_until <= effective_now,
                    )
                )
                .order_by(FAN_TURNS.c.quiet_until, FAN_TURNS.c.id)
                .limit(max(1, min(int(limit), 500)))
                .with_for_update()
            ).mappings().all()
            ids = [int(row["id"]) for row in rows]
            if ids:
                connection.execute(
                    update(FAN_TURNS)
                    .where(FAN_TURNS.c.id.in_(ids))
                    .values(
                        status="ready",
                        closed_at=effective_now,
                        updated_at=effective_now,
                    )
                )
            return [self._turn(connection, turn_id) for turn_id in ids]

    def cancel_open_for_fan(
        self,
        *,
        creator_id: str,
        fan_id: str,
        reason: str,
    ) -> int:
        now = utcnow()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(FAN_TURNS)
                .where(
                    and_(
                        FAN_TURNS.c.creator_id == creator_id,
                        FAN_TURNS.c.fan_id == fan_id,
                        FAN_TURNS.c.status.in_(
                            ["collecting", "ready", "planned"]
                        ),
                    )
                )
                .values(
                    status="cancelled",
                    cancel_reason=str(reason)[:128],
                    closed_at=now,
                    updated_at=now,
                )
            )
        return int(result.rowcount or 0)

    def assembled_text(self, turn_id: int) -> str:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(INBOUND_MESSAGES.c.content)
                .select_from(
                    FAN_TURN_INBOUND_LINKS.join(
                        INBOUND_MESSAGES,
                        FAN_TURN_INBOUND_LINKS.c.inbound_message_id
                        == INBOUND_MESSAGES.c.id,
                    )
                )
                .where(FAN_TURN_INBOUND_LINKS.c.turn_id == int(turn_id))
                .order_by(
                    INBOUND_MESSAGES.c.provider_created_at,
                    INBOUND_MESSAGES.c.id,
                )
            ).scalars().all()
        return "\n".join(str(value).strip() for value in rows if str(value).strip())

    @staticmethod
    def _turn(connection, turn_id: int) -> dict:
        row = connection.execute(
            select(FAN_TURNS).where(FAN_TURNS.c.id == int(turn_id))
        ).mappings().one()
        return dict(row)

    @staticmethod
    def _resequence(connection, turn_id: int) -> None:
        rows = connection.execute(
            select(
                FAN_TURN_INBOUND_LINKS.c.inbound_message_id,
                INBOUND_MESSAGES.c.provider_created_at,
                INBOUND_MESSAGES.c.id,
            )
            .select_from(
                FAN_TURN_INBOUND_LINKS.join(
                    INBOUND_MESSAGES,
                    FAN_TURN_INBOUND_LINKS.c.inbound_message_id
                    == INBOUND_MESSAGES.c.id,
                )
            )
            .where(FAN_TURN_INBOUND_LINKS.c.turn_id == int(turn_id))
            .order_by(
                INBOUND_MESSAGES.c.provider_created_at,
                INBOUND_MESSAGES.c.id,
            )
        ).all()
        connection.execute(
            update(FAN_TURN_INBOUND_LINKS)
            .where(FAN_TURN_INBOUND_LINKS.c.turn_id == int(turn_id))
            .values(
                position=FAN_TURN_INBOUND_LINKS.c.position + 1_000
            )
        )
        for position, row in enumerate(rows, start=1):
            connection.execute(
                update(FAN_TURN_INBOUND_LINKS)
                .where(
                    and_(
                        FAN_TURN_INBOUND_LINKS.c.turn_id == int(turn_id),
                        FAN_TURN_INBOUND_LINKS.c.inbound_message_id
                        == int(row.inbound_message_id),
                    )
                )
                .values(position=position)
            )


class HumanResponsePlanRepository:
    """Persist shadow plans; this repository never touches the live outbox."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def save_shadow_plan(
        self,
        *,
        turn_id: int,
        creator_id: str,
        fan_id: str,
        decision: HumanDeliveryDecision,
        prompt_fingerprint: str,
        compilation_report: dict,
        model: str,
        planner_version: str = "human-delivery-v1",
        current_decision_id: int | None = None,
        first_available_at: datetime | None = None,
        model_calls: int = 0,
        latency_ms: int = 0,
    ) -> tuple[dict, bool]:
        now = utcnow()
        available = first_available_at or now
        values = {
            "turn_id": int(turn_id),
            "creator_id": creator_id,
            "fan_id": fan_id,
            "current_decision_id": current_decision_id,
            "status": "shadow",
            "shadow": True,
            "model": str(model)[:128],
            "planner_version": str(planner_version)[:64],
            "prompt_fingerprint": str(prompt_fingerprint)[:64],
            "decision_fingerprint": decision.fingerprint,
            "understanding": {
                "language": decision.language,
                "fan_emotion": decision.fan_emotion,
                "relationship_stage": decision.relationship_stage,
                "unresolved_topic": decision.unresolved_topic,
            },
            "strategy": {
                "primary_act": decision.primary_act,
                "secondary_act": decision.secondary_act,
                "should_ask_question": decision.should_ask_question,
                "safety_class": decision.safety_class,
            },
            "delivery": {
                "casing_mode": decision.casing_mode,
                "energy": decision.energy,
                "bubble_count": len(decision.bubbles),
            },
            "quality": dict(decision.quality),
            "compilation_report": dict(compilation_report),
            "model_calls": max(0, int(model_calls)),
            "latency_ms": max(0, int(latency_ms)),
            "created_at": now,
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            statement = self._insert(HUMAN_RESPONSE_PLANS).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=["turn_id"]
            )
            result = connection.execute(statement)
            created = result.rowcount == 1
            plan = connection.execute(
                select(HUMAN_RESPONSE_PLANS).where(
                    HUMAN_RESPONSE_PLANS.c.turn_id == int(turn_id)
                )
            ).mappings().one()
            plan_id = int(plan["id"])
            if created:
                for index, bubble in enumerate(decision.bubbles, start=1):
                    if index > 1:
                        minimum, maximum = (
                            (2, 8) if index == 2 else (3, 12)
                        )
                        digest = int(
                            hashlib.sha256(
                                f"{decision.fingerprint}:{index}".encode()
                            ).hexdigest()[:8],
                            16,
                        )
                        delay = minimum + digest % (maximum - minimum + 1)
                        available = available + timedelta(seconds=delay)
                    idempotency_key = hashlib.sha256(
                        (
                            f"{creator_id}:{turn_id}:{index}:"
                            f"{decision.fingerprint}"
                        ).encode("utf-8")
                    ).hexdigest()
                    connection.execute(
                        insert(HUMAN_RESPONSE_BUBBLES).values(
                            plan_id=plan_id,
                            bubble_index=index,
                            role=bubble.role,
                            content=bubble.text,
                            status="shadow",
                            available_at=available,
                            idempotency_key=idempotency_key,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                connection.execute(
                    update(FAN_TURNS)
                    .where(FAN_TURNS.c.id == int(turn_id))
                    .values(status="planned", updated_at=now)
                )
            return dict(plan), created

    def cancel_plan(self, plan_id: int, *, reason: str) -> int:
        now = utcnow()
        with self.engine.begin() as connection:
            connection.execute(
                update(HUMAN_RESPONSE_PLANS)
                .where(
                    and_(
                        HUMAN_RESPONSE_PLANS.c.id == int(plan_id),
                        HUMAN_RESPONSE_PLANS.c.status.in_(
                            ["planned", "shadow"]
                        ),
                    )
                )
                .values(
                    status="cancelled",
                    cancel_reason=str(reason)[:128],
                    updated_at=now,
                )
            )
            result = connection.execute(
                update(HUMAN_RESPONSE_BUBBLES)
                .where(
                    and_(
                        HUMAN_RESPONSE_BUBBLES.c.plan_id == int(plan_id),
                        HUMAN_RESPONSE_BUBBLES.c.status.in_(
                            ["planned", "shadow"]
                        ),
                    )
                )
                .values(
                    status="cancelled",
                    cancellation_reason=str(reason)[:128],
                    updated_at=now,
                )
            )
        return int(result.rowcount or 0)

    def metrics(self, *, creator_id: str) -> dict:
        with self.engine.connect() as connection:
            plan_rows = connection.execute(
                select(
                    HUMAN_RESPONSE_PLANS.c.status,
                    func.count(HUMAN_RESPONSE_PLANS.c.id),
                )
                .where(
                    HUMAN_RESPONSE_PLANS.c.creator_id == creator_id
                )
                .group_by(HUMAN_RESPONSE_PLANS.c.status)
            ).all()
            bubble_counts = connection.execute(
                select(
                    HUMAN_RESPONSE_PLANS.c.id,
                    func.count(HUMAN_RESPONSE_BUBBLES.c.id),
                )
                .select_from(
                    HUMAN_RESPONSE_PLANS.join(
                        HUMAN_RESPONSE_BUBBLES,
                        HUMAN_RESPONSE_PLANS.c.id
                        == HUMAN_RESPONSE_BUBBLES.c.plan_id,
                    )
                )
                .where(
                    HUMAN_RESPONSE_PLANS.c.creator_id == creator_id
                )
                .group_by(HUMAN_RESPONSE_PLANS.c.id)
            ).all()
        distribution = {"1": 0, "2": 0, "3": 0}
        for _, count in bubble_counts:
            distribution[str(min(max(int(count), 1), 3))] += 1
        average = (
            sum(int(count) for _, count in bubble_counts)
            / len(bubble_counts)
            if bubble_counts
            else 0.0
        )
        return {
            "plans_by_status": {
                str(status): int(count)
                for status, count in plan_rows
            },
            "bubble_distribution": distribution,
            "average_bubbles": round(average, 3),
            "outbox_writes": 0,
        }

    def _insert(self, table):
        if self.engine.dialect.name == "postgresql":
            return pg_insert(table)
        if self.engine.dialect.name == "sqlite":
            return sqlite_insert(table)
        raise RuntimeError(
            f"Unsupported database dialect: {self.engine.dialect.name}"
        )
