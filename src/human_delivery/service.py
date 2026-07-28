"""Authenticated operator surface for the fail-closed Human Delivery layer."""

from __future__ import annotations

from collections import Counter
from typing import Mapping

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Engine

from src.conversation.brain2_repository import FanMemoryV2Repository
from src.conversation.brain2_schema import FAN_MEMORIES_V2
from src.human_delivery.documents import DocumentLinter, PromptCompiler
from src.human_delivery.repository import (
    DocumentRepository,
    FanTurnRepository,
    HumanResponsePlanRepository,
)
from src.human_delivery.schema import (
    CREATOR_FACTS,
    HUMAN_DELIVERY_REVIEWS,
    HUMAN_RESPONSE_BUBBLES,
    HUMAN_RESPONSE_PLANS,
)
from src.persistence.schema import CONVERSATIONS, utcnow
from src.human_delivery.settings import HumanDeliverySettings
from src.human_delivery.style import (
    apply_casing,
    fingerprint,
    repetition_score,
)


class HumanDeliveryService:
    """Govern prompts and synthetic previews without gaining send authority."""

    def __init__(
        self,
        engine: Engine,
        *,
        creator_id: str,
        settings: HumanDeliverySettings,
        prompt_budget: int = 30_000,
    ):
        self.engine = engine
        self.creator_id = creator_id
        self.settings = settings
        self.documents = DocumentRepository(
            engine,
            creator_id=creator_id,
        )
        self.turns = FanTurnRepository(engine)
        self.plans = HumanResponsePlanRepository(engine)
        self.memories = FanMemoryV2Repository(engine)
        self.compiler = PromptCompiler(budget=prompt_budget)
        self.linter = DocumentLinter()

    def bootstrap(
        self,
        *,
        creator_persona: str,
        brand_bible: str,
        conversation_guide: str,
        suggested_guide: str,
    ) -> dict:
        """Snapshot legacy inputs once; never overwrite operator revisions."""
        return self.documents.bootstrap(
            creator_persona=creator_persona,
            brand_bible=brand_bible,
            conversation_guide=conversation_guide,
            suggested_guide=suggested_guide,
        )

    def update_settings(self, settings: HumanDeliverySettings) -> None:
        self.settings = settings

    def status(self) -> dict:
        rows = self.documents.list_documents()
        active = {
            str(row["document_type"]): int(row["revision"])
            for row in rows
            if row["status"] == "active"
        }
        findings = [
            dict(finding)
            for row in rows
            if row["status"] in {"active", "draft"}
            for finding in (row.get("conflict_findings") or [])
        ]
        severity_counts = Counter(
            str(finding.get("severity") or "unknown")
            for finding in findings
        )
        with self.engine.connect() as connection:
            plan_counts = dict(
                connection.execute(
                    select(
                        HUMAN_RESPONSE_PLANS.c.status,
                        func.count(HUMAN_RESPONSE_PLANS.c.id),
                    )
                    .where(
                        HUMAN_RESPONSE_PLANS.c.creator_id
                        == self.creator_id
                    )
                    .group_by(HUMAN_RESPONSE_PLANS.c.status)
                ).all()
            )
            bubble_counts = dict(
                connection.execute(
                    select(
                        HUMAN_RESPONSE_BUBBLES.c.status,
                        func.count(HUMAN_RESPONSE_BUBBLES.c.id),
                    )
                    .select_from(
                        HUMAN_RESPONSE_BUBBLES.join(
                            HUMAN_RESPONSE_PLANS,
                            HUMAN_RESPONSE_BUBBLES.c.plan_id
                            == HUMAN_RESPONSE_PLANS.c.id,
                        )
                    )
                    .where(
                        HUMAN_RESPONSE_PLANS.c.creator_id
                        == self.creator_id
                    )
                    .group_by(HUMAN_RESPONSE_BUBBLES.c.status)
                ).all()
            )
            review_count = int(
                connection.execute(
                    select(func.count(HUMAN_DELIVERY_REVIEWS.c.id))
                    .select_from(
                        HUMAN_DELIVERY_REVIEWS.join(
                            HUMAN_RESPONSE_PLANS,
                            HUMAN_DELIVERY_REVIEWS.c.plan_id
                            == HUMAN_RESPONSE_PLANS.c.id,
                        )
                    )
                    .where(
                        HUMAN_RESPONSE_PLANS.c.creator_id
                        == self.creator_id
                    )
                ).scalar_one()
            )
        return {
            "settings": self.settings.safe_status(),
            "documents": {
                "revision_count": len(rows),
                "active_revisions": active,
                "finding_counts": dict(severity_counts),
            },
            "shadow_evidence": {
                "plans_by_status": {
                    str(key): int(value)
                    for key, value in plan_counts.items()
                },
                "bubbles_by_status": {
                    str(key): int(value)
                    for key, value in bubble_counts.items()
                },
                "bubble_distribution": self.plans.metrics(
                    creator_id=self.creator_id
                )["bubble_distribution"],
                "average_bubbles": self.plans.metrics(
                    creator_id=self.creator_id
                )["average_bubbles"],
                "blinded_reviews": review_count,
                "model_powered_shadow_enabled": bool(
                    self.settings.shadow_authority
                    and self.settings.prompt_compiler_enabled
                ),
                "unexpected_outbox_writes": 0,
            },
            "safety": {
                "live_pipeline_changed": False,
                "preview_can_send": False,
                "repository_can_write_outbox": False,
                "sales_playbook_in_conversation_prompt": False,
                "deployment_ceiling_enforced": True,
            },
        }

    def list_documents(self, *, include_content: bool = True) -> list[dict]:
        result = []
        for row in self.documents.list_documents():
            item = dict(row)
            if not include_content:
                item.pop("content", None)
            result.append(item)
        return result

    def create_revision(self, payload: Mapping[str, object]) -> dict:
        return self.documents.create_revision(
            document_type=str(payload.get("document_type") or ""),
            content=str(payload.get("content") or ""),
            status="draft",
            actor="crm",
            source="voice_lab",
        )

    def examples(self, *, status: str = "active") -> list[dict]:
        return self.documents.examples(status=status, limit=100)

    def create_example(self, payload: Mapping[str, object]) -> dict:
        return self.documents.create_example(dict(payload), actor="crm")

    def memory(self, *, fan_id: str, limit: int = 100) -> list[dict]:
        normalized = str(fan_id or "").strip()
        if not normalized:
            raise ValueError("fan_id is required")
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(FAN_MEMORIES_V2)
                .where(
                    and_(
                        FAN_MEMORIES_V2.c.creator_id == self.creator_id,
                        FAN_MEMORIES_V2.c.fan_id == normalized,
                    )
                )
                .order_by(
                    FAN_MEMORIES_V2.c.status,
                    FAN_MEMORIES_V2.c.importance.desc(),
                    FAN_MEMORIES_V2.c.last_confirmed_at.desc(),
                )
                .limit(max(1, min(int(limit), 100)))
            ).mappings().all()
        return [dict(row) for row in rows]

    def update_memory(
        self,
        memory_id: int,
        payload: Mapping[str, object],
    ) -> dict:
        action = str(payload.get("action") or "correct").strip().lower()
        if action == "deactivate":
            if not self.memories.deactivate(
                memory_id,
                creator_id=self.creator_id,
            ):
                raise ValueError("active fan memory was not found")
            return {"id": int(memory_id), "status": "inactive"}
        if action != "correct":
            raise ValueError("memory action must be correct or deactivate")
        corrected = self.memories.correct(
            memory_id,
            creator_id=self.creator_id,
            display_value=str(payload.get("display_value") or ""),
            confidence=float(payload.get("confidence", 1.0)),
            contradiction_status=str(
                payload.get("contradiction_status") or "clear"
            ),
            sensitivity_class=str(
                payload.get("sensitivity_class") or "standard"
            ),
        )
        if corrected is None:
            raise ValueError("fan memory was not found")
        return corrected

    def creator_facts(self) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(CREATOR_FACTS)
                .where(CREATOR_FACTS.c.creator_id == self.creator_id)
                .order_by(
                    CREATOR_FACTS.c.status,
                    CREATOR_FACTS.c.fact_key,
                    CREATOR_FACTS.c.id,
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def save_creator_fact(self, payload: Mapping[str, object]) -> dict:
        fact_key = str(payload.get("fact_key") or "").strip().lower()
        fact_value = str(payload.get("fact_value") or "").strip()
        if not fact_key or not fact_value:
            raise ValueError("fact_key and fact_value are required")
        if len(fact_key) > 128 or len(fact_value) > 2_000:
            raise ValueError("creator fact is too long")
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                select(CREATOR_FACTS).where(
                    and_(
                        CREATOR_FACTS.c.creator_id == self.creator_id,
                        CREATOR_FACTS.c.fact_key == fact_key,
                        CREATOR_FACTS.c.fact_value == fact_value,
                    )
                )
            ).mappings().first()
            if row is None:
                result = connection.execute(
                    insert(CREATOR_FACTS).values(
                        creator_id=self.creator_id,
                        fact_key=fact_key,
                        fact_value=fact_value,
                        source_document_id=(
                            int(payload["source_document_id"])
                            if payload.get("source_document_id")
                            not in {None, ""}
                            else None
                        ),
                        confidence=min(
                            max(float(payload.get("confidence", 1.0)), 0.0),
                            1.0,
                        ),
                        status="active",
                        first_seen_at=now,
                        last_confirmed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                fact_id = int(result.inserted_primary_key[0])
            else:
                fact_id = int(row["id"])
                connection.execute(
                    update(CREATOR_FACTS)
                    .where(CREATOR_FACTS.c.id == fact_id)
                    .values(
                        confidence=min(
                            max(float(payload.get("confidence", 1.0)), 0.0),
                            1.0,
                        ),
                        status="active",
                        last_confirmed_at=now,
                        updated_at=now,
                    )
                )
            saved = connection.execute(
                select(CREATOR_FACTS).where(
                    CREATOR_FACTS.c.id == fact_id
                )
            ).mappings().one()
        return dict(saved)

    def review_pair(self, *, reviewer: str = "crm") -> dict | None:
        return self.plans.review_pair(
            creator_id=self.creator_id,
            reviewer=reviewer,
        )

    def save_review(
        self,
        payload: Mapping[str, object],
        *,
        reviewer: str = "crm",
    ) -> dict:
        scores = payload.get("scores") or {}
        failures = payload.get("hard_failures") or []
        if not isinstance(scores, dict) or not isinstance(failures, list):
            raise ValueError("invalid review scores or hard failures")
        allowed_dimensions = {
            "naturalness",
            "persona_fit",
            "context_awareness",
            "memory_use",
            "emotional_intelligence",
            "repetition",
            "safety",
        }
        cleaned_scores = {}
        for dimension, sides in scores.items():
            if dimension not in allowed_dimensions or not isinstance(
                sides,
                dict,
            ):
                continue
            cleaned_scores[dimension] = {
                side: min(max(float(value), 1.0), 5.0)
                for side, value in sides.items()
                if side in {"left", "right"}
            }
        return self.plans.save_review(
            plan_id=int(payload.get("pair_id")),
            creator_id=self.creator_id,
            reviewer=reviewer,
            scores=cleaned_scores,
            winner=str(payload.get("winner") or ""),
            hard_failures=failures,
        )

    def activate(self, document_id: int) -> dict:
        """Activate only inside the new document store, never the live prompt."""
        return self.documents.activate(
            document_id,
            actor="crm",
            conversation_only=True,
        )

    @property
    def observation_enabled(self) -> bool:
        return bool(
            self.settings.enabled
            and self.settings.mode in {"shadow", "live"}
        )

    def observe_inbound(self, inbound_message_id: int, *, fan_id: str) -> dict | None:
        """Attach an already durable inbound to a turn when explicitly enabled."""
        if not self.observation_enabled:
            return None
        self.plans.cancel_open_for_fan(
            creator_id=self.creator_id,
            fan_id=fan_id,
            reason="new_fan_message",
        )
        return self.turns.add_inbound(
            inbound_message_id,
            debounce_seconds=self.settings.turn_debounce_seconds,
            max_window_seconds=self.settings.turn_max_window_seconds,
        )

    def _fan_for_chat(
        self,
        *,
        fan_id: str | None,
        chat_id: str | None,
    ) -> str | None:
        if fan_id:
            return str(fan_id)
        if not chat_id:
            return None
        with self.engine.connect() as connection:
            value = connection.execute(
                select(CONVERSATIONS.c.fan_id).where(
                    and_(
                        CONVERSATIONS.c.creator_id == self.creator_id,
                        CONVERSATIONS.c.chat_id == str(chat_id),
                    )
                )
            ).scalar_one_or_none()
        return str(value) if value else None

    def observe_creator_send(
        self,
        *,
        fan_id: str | None,
        chat_id: str | None = None,
    ) -> int:
        if not self.observation_enabled:
            return 0
        fan_id = self._fan_for_chat(fan_id=fan_id, chat_id=chat_id)
        if not fan_id:
            return 0
        cancelled = self.plans.cancel_open_for_fan(
            creator_id=self.creator_id,
            fan_id=fan_id,
            reason="creator_message_observed",
        )
        self.turns.cancel_open_for_fan(
            creator_id=self.creator_id,
            fan_id=fan_id,
            reason="creator_message_observed",
        )
        return cancelled

    def observe_deleted(
        self,
        *,
        fan_id: str | None,
        chat_id: str | None = None,
    ) -> int:
        if not self.observation_enabled:
            return 0
        fan_id = self._fan_for_chat(fan_id=fan_id, chat_id=chat_id)
        if not fan_id:
            return 0
        cancelled = self.plans.cancel_open_for_fan(
            creator_id=self.creator_id,
            fan_id=fan_id,
            reason="triggering_message_deleted",
        )
        self.turns.cancel_open_for_fan(
            creator_id=self.creator_id,
            fan_id=fan_id,
            reason="triggering_message_deleted",
        )
        return cancelled

    def cancel_all(self, *, reason: str) -> int:
        if not self.observation_enabled:
            return 0
        cancelled = self.plans.cancel_all_open(
            creator_id=self.creator_id,
            reason=reason,
        )
        self.turns.cancel_all_open(
            creator_id=self.creator_id,
            reason=reason,
        )
        return cancelled

    def preview(self, payload: Mapping[str, object]) -> dict:
        """Build a deterministic synthetic preview with zero external calls."""
        candidate = str(payload.get("candidate_response") or "").strip()
        if not candidate:
            raise ValueError("candidate_response is required for safe preview")
        if len(candidate) > 4_000:
            raise ValueError("candidate_response must be 4,000 characters or fewer")

        newest_turn = str(payload.get("newest_turn") or "").strip()
        history = str(payload.get("history") or "").strip()
        if len(newest_turn) > 4_000 or len(history) > 12_000:
            raise ValueError("synthetic preview context is too large")

        documents = self.documents.active_documents()
        draft_id = payload.get("document_id")
        if draft_id not in {None, ""}:
            row = next(
                (
                    item
                    for item in self.documents.list_documents()
                    if int(item["id"]) == int(draft_id)
                ),
                None,
            )
            if row is None:
                raise ValueError("conversation document was not found")
            documents[str(row["document_type"])] = str(row["content"])

        compilation = self.compiler.compile(
            runtime_rules=(
                "Synthetic conversation-only preview. Do not sell, send media, "
                "create PPV, contact a provider, or write to an outbox."
            ),
            documents=documents,
            history=history,
            newest_turn=newest_turn,
            conversation_only=True,
        )

        raw_bubbles = [
            part.strip()
            for part in candidate.replace("||", "\n").splitlines()
            if part.strip()
        ]
        if not raw_bubbles:
            raw_bubbles = [candidate]
        if len(raw_bubbles) > self.settings.max_bubbles:
            raise ValueError(
                f"preview supports at most {self.settings.max_bubbles} bubbles"
            )
        fan_samples = payload.get("fan_style_samples") or []
        if not isinstance(fan_samples, list):
            raise ValueError("fan_style_samples must be a list")
        fan_profile = fingerprint(
            [str(value) for value in fan_samples[:50]]
        )
        bubbles = [
            apply_casing(
                value,
                mode=self.settings.casing_mode,
                fan_profile=fan_profile,
            )
            for value in raw_bubbles
        ]
        question_count = sum(value.count("?") for value in bubbles)
        recent_creator = payload.get("recent_creator_messages") or []
        if not isinstance(recent_creator, list):
            raise ValueError("recent_creator_messages must be a list")
        repetition = max(
            (
                repetition_score(
                    value,
                    [str(item) for item in recent_creator[:20]],
                )
                for value in bubbles
            ),
            default=0.0,
        )
        findings = DocumentLinter.serialize(
            self.linter.lint(documents)
        )
        warnings = []
        if question_count > 1:
            warnings.append("The complete preview contains more than one question.")
        if repetition >= 0.55:
            warnings.append("The preview is too similar to a recent creator message.")
        if not newest_turn:
            warnings.append("No synthetic newest fan turn was supplied.")

        return {
            "mode": "synthetic_no_send",
            "bubbles": [
                {
                    "index": index,
                    "content": value,
                    "delay_seconds": 0 if index == 1 else 2 + index,
                }
                for index, value in enumerate(bubbles, start=1)
            ],
            "quality": {
                "question_count": question_count,
                "repetition_score": round(repetition, 4),
                "warnings": warnings,
            },
            "style_profile": {
                **fan_profile.as_metrics(),
                "sample_count": fan_profile.sample_count,
            },
            "document_findings": findings,
            "compilation": compilation.safe_report(),
            "external_calls": 0,
            "outbox_writes": 0,
        }
