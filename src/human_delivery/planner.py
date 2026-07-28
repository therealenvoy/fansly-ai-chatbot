"""One-call, shadow-only planner for future controlled evaluation."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Protocol

from src.human_delivery.contracts import (
    DeliveryBubble,
    HumanDeliveryDecision,
)
from src.human_delivery.repository import (
    DocumentRepository,
    HumanResponsePlanRepository,
)
from src.human_delivery.settings import HumanDeliverySettings
from src.human_delivery.style import (
    apply_casing,
    apply_rare_typo,
    repetition_score,
)
from src.human_delivery.documents import PromptCompiler


class JsonCompletionProvider(Protocol):
    def complete_json(self, prompt: str) -> str:
        """Return one JSON response from one model request."""


class HumanDeliveryPlanner:
    """Create an inert response plan; never writes to the production outbox."""

    def __init__(
        self,
        *,
        documents: DocumentRepository,
        plans: HumanResponsePlanRepository,
        compiler: PromptCompiler,
        settings: HumanDeliverySettings,
        provider: JsonCompletionProvider,
        model: str,
    ):
        self.documents = documents
        self.plans = plans
        self.compiler = compiler
        self.settings = settings
        self.provider = provider
        self.model = str(model)

    def plan_shadow(
        self,
        *,
        turn_id: int,
        creator_id: str,
        fan_id: str,
        newest_turn: str,
        history: str = "",
        creator_facts: list[str] | None = None,
        fan_memory: list[str] | None = None,
        contact_policy: str = "inbound conversation reply only",
        recent_creator_messages: list[str] | None = None,
    ) -> dict:
        if not (
            self.settings.shadow_authority
            and self.settings.prompt_compiler_enabled
        ):
            return {
                "status": "disabled",
                "model_calls": 0,
                "outbox_writes": 0,
            }
        sample = int.from_bytes(
            hashlib.sha256(
                f"{creator_id}:{fan_id}:{turn_id}".encode("utf-8")
            ).digest()[:4],
            "big",
        ) % 100
        if sample >= self.settings.shadow_percent:
            return {
                "status": "not_sampled",
                "model_calls": 0,
                "outbox_writes": 0,
            }
        compilation = self.compiler.compile(
            runtime_rules=(
                "Return only the validated Human Delivery JSON contract. "
                "Conversation-only: no sales, PPV, price, tip, media, or "
                "unsupported factual claims. Never include private reasoning."
            ),
            documents=self.documents.active_documents(),
            creator_facts=creator_facts or [],
            contact_policy=contact_policy,
            fan_memory=fan_memory or [],
            history=history,
            newest_turn=newest_turn,
            examples=self.documents.examples(status="active", limit=12),
            conversation_only=True,
        )
        raw = self.provider.complete_json(compilation.prompt)
        decision = HumanDeliveryDecision.from_model_output(
            raw,
            max_bubbles=self.settings.max_bubbles,
            conversation_only=True,
            verified_creator_facts={
                str(value).strip().casefold()
                for value in (creator_facts or [])
                if str(value).strip()
            },
        )
        if decision is None:
            return {
                "status": "fallback",
                "reason": "invalid_structured_output",
                "model_calls": 1,
                "outbox_writes": 0,
            }
        styled_bubbles = tuple(
            DeliveryBubble(
                role=bubble.role,
                text=apply_rare_typo(
                    apply_casing(
                        bubble.text,
                        mode=decision.casing_mode,
                    ),
                    enabled=self.settings.allow_typos,
                    seed=f"{turn_id}:{index}",
                ),
            )
            for index, bubble in enumerate(decision.bubbles, start=1)
        )
        decision = replace(decision, bubbles=styled_bubbles)
        recent = [str(value) for value in (recent_creator_messages or [])]
        if (
            decision.should_ask_question
            and len(recent) >= 2
            and all("?" in value for value in recent[-2:])
        ):
            return {
                "status": "fallback",
                "reason": "question_fatigue",
                "model_calls": 1,
                "outbox_writes": 0,
            }
        if any(
            repetition_score(bubble.text, recent) >= 0.55
            for bubble in decision.bubbles
        ):
            return {
                "status": "fallback",
                "reason": "semantic_repetition",
                "model_calls": 1,
                "outbox_writes": 0,
            }
        plan, created = self.plans.save_shadow_plan(
            turn_id=turn_id,
            creator_id=creator_id,
            fan_id=fan_id,
            decision=decision,
            prompt_fingerprint=compilation.fingerprint,
            compilation_report=compilation.safe_report(),
            model=self.model,
            model_calls=1,
        )
        return {
            "status": "shadow_planned",
            "plan_id": int(plan["id"]),
            "created": bool(created),
            "model_calls": 1,
            "outbox_writes": 0,
        }
