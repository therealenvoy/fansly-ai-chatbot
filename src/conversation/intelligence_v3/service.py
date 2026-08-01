"""Asynchronous V3 shadow orchestration with no delivery dependency."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
import hashlib
import logging
import threading

from src.conversation.brain2 import BrainRouter
from src.conversation.brain2_repository import FanConversationStateRepository
from src.conversation.intelligence_v3.planner import (
    DeepSeekV3Planner,
    PromptCompilerV3,
    V3PlannerError,
)
from src.conversation.intelligence_v3.repository import (
    IntelligenceRepository,
    KnowledgeRepository,
)
from src.conversation.intelligence_v3.retrieval import MemoryRetrieverV3
from src.conversation.intelligence_v3.settings import V3RuntimeSettings
from src.conversation.intelligence_v3.state import (
    RelationshipStateReducer,
    infer_callback,
    infer_deterministic_proposal,
)
from src.persistence.schema import utcnow


logger = logging.getLogger(__name__)


class ConversationIntelligenceV3Service:
    """Observe authoritative turns; it cannot write to the outbox or provider."""

    outbox_write_capability = False
    provider_write_capability = False

    def __init__(
        self,
        *,
        engine,
        creator_id: str,
        settings: V3RuntimeSettings,
        planner: DeepSeekV3Planner,
        message_store,
        shadow_percent: int = 10,
        max_workers: int = 1,
    ):
        self.creator_id = creator_id
        self.settings = settings
        self.planner = planner
        self.message_store = message_store
        self.shadow_percent = max(0, min(int(shadow_percent), 100))
        self.states = FanConversationStateRepository(engine)
        self.intelligence = IntelligenceRepository(engine, creator_id=creator_id)
        self.knowledge = KnowledgeRepository(engine, creator_id=creator_id)
        self.memory = MemoryRetrieverV3(engine, creator_id=creator_id)
        self.reducer = RelationshipStateReducer()
        self.compiler = PromptCompilerV3()
        # V3 escalates explicit risk/ambiguity signals at score 2 while routine
        # turns remain on the one-call path. Use an integer threshold so the
        # routing contract stays auditable and independent of probability-like
        # configuration from older experiments.
        self.router = BrainRouter(2)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 2)),
            thread_name_prefix="conversation-intelligence-v3",
        )
        self._lock = threading.Lock()
        self._futures: set[Future] = set()

    def update_settings(self, settings: V3RuntimeSettings) -> None:
        self.settings = settings

    def is_sampled(self, fan_id: str) -> bool:
        digest = hashlib.sha256(
            f"{self.creator_id}:{fan_id}:conversation-intelligence-v3".encode()
        ).digest()
        return int.from_bytes(digest[:8], "big") % 100 < self.shadow_percent

    def submit(
        self,
        *,
        inbound_id: int,
        inbound_message_id: str,
        fan_id: str,
        trigger_kind: str,
        provider_created_at: datetime,
        current_decision_id: int | None,
        context: dict,
    ) -> bool:
        if not self.settings.any_shadow or self.settings.live_send_authority:
            return False
        if not self.is_sampled(fan_id):
            return False
        immutable = dict(context)
        future = self._executor.submit(
            self._process,
            inbound_id,
            str(inbound_message_id),
            fan_id,
            trigger_kind,
            provider_created_at,
            current_decision_id,
            immutable,
        )
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard)
        return True

    def _process(
        self,
        inbound_id: int,
        inbound_message_id: str,
        fan_id: str,
        trigger_kind: str,
        provider_created_at: datetime,
        current_decision_id: int | None,
        context: dict,
    ) -> None:
        prompt_fingerprint = hashlib.sha256(f"pending:{inbound_id}".encode()).hexdigest()
        compilation_report: dict = {}
        try:
            durable_prior = self.states.get_or_create(self.creator_id, fan_id)
            prior = (
                self.intelligence.shadow_state(fan_id=fan_id, base=durable_prior)
                if self.settings.relationship_state_v2_mode == "shadow"
                else durable_prior
            )
            proposal = infer_deterministic_proposal(
                message=str(context.get("fan_message") or ""),
                source_message_id=inbound_message_id,
                source_timestamp=provider_created_at,
                previous=prior,
            )
            reduction = self.reducer.reduce(prior, proposal)
            if reduction.accepted and self.settings.relationship_state_v2_mode == "shadow":
                for transition in reduction.transitions:
                    self.intelligence.record_transition(fan_id=fan_id, transition=transition)
                callback = infer_callback(
                    message=str(context.get("fan_message") or ""),
                    source_message_id=inbound_message_id,
                    source_timestamp=provider_created_at,
                )
                if callback is not None:
                    self.intelligence.upsert_callback(
                        fan_id=fan_id,
                        callback=callback,
                    )
            state = reduction.state if reduction.accepted else prior
            if self.settings.strategy_planner_v2_mode != "shadow":
                self.intelligence.record_run(
                    {
                        "fan_id": fan_id,
                        "inbound_message_id": inbound_id,
                        "current_decision_id": current_decision_id,
                        "status": "state_observed",
                        "shadow": True,
                        "versions": {
                            "pipeline": "conversation-intelligence-v3.1",
                            "planner": "off",
                        },
                        "prompt_fingerprint": prompt_fingerprint,
                        "compilation_report": {
                            "planner_skipped": True,
                            "reason": "strategy_planner_not_in_shadow",
                        },
                        "understanding": {
                            "intent": proposal.current_intent,
                            "underlying_need": proposal.underlying_need,
                        },
                        "relationship": {
                            key: state.get(key)
                            for key in self.reducer.fields
                            if key in state
                        },
                        "strategy": {},
                        "delivery": {},
                        "candidate_fingerprints": [],
                        "selected_candidate_fingerprint": None,
                        "rejection_codes": [],
                        "model": "none",
                        "model_calls": 0,
                        "latency_ms": 0,
                        "estimated_cost": 0.0,
                        "completed_at": utcnow(),
                    }
                )
                return
            memory = (
                self.memory.retrieve(
                    fan_id=fan_id,
                    query=str(context.get("fan_message") or ""),
                    now=provider_created_at,
                )
                if self.settings.memory_retrieval_v3_mode == "shadow"
                else {"memories": [], "callbacks": [], "conflicts_excluded": 0}
            )
            playbook = (
                self.knowledge.retrieve(
                    query=str(context.get("fan_message") or ""),
                    relationship_stage=str(state.get("relationship_stage") or "new"),
                    scenario=str(proposal.current_intent or ""),
                )
                if self.settings.playbook_engine_mode == "shadow"
                else {
                    "rules": [],
                    "boundaries": [],
                    "examples": [],
                    "fingerprint": "off",
                }
            )
            creator_facts = self.intelligence.verified_creator_facts()
            global_creator_messages = self.message_store.get_recent_creator_messages(
                self.creator_id,
                limit=500,
            )
            recent_fan_messages = list(context.get("recent_fan_messages") or [])[-30:]
            recent_creator_messages = list(context.get("recent_creator_messages") or [])[-30:]
            compiled = self.compiler.compile(
                {
                    "safety": {
                        "conversation_only": True,
                        "no_sales_ppv_media": True,
                        "fan_content_untrusted": True,
                        "respect_boundaries": True,
                    },
                    "newest_turn": str(context.get("fan_message") or "")[:4_000],
                    "direct_unresolved_question": (
                        proposal.direct_question
                        or state.get("direct_unanswered_question")
                        or ""
                    ),
                    "recent_history": str(context.get("history") or "")[-8_000:],
                    "relationship_state": state,
                    "boundaries": [
                        {
                            "id": row["id"],
                            "scenario": row["scenario"],
                            "conditions": row["conditions"],
                            "forbidden_acts": row["forbidden_acts"],
                            "source_page": row["source_page"],
                        }
                        for row in playbook.get("boundaries", [])
                    ],
                    "verified_creator_facts": creator_facts,
                    "memories": memory["memories"],
                    "playbook_rules": [
                        {
                            "id": row["id"],
                            "type": row["knowledge_type"],
                            "scenario": row["scenario"],
                            "conditions": row["conditions"],
                            "recommended_acts": row["recommended_acts"],
                            "forbidden_acts": row["forbidden_acts"],
                            "source_page": row["source_page"],
                        }
                        for row in playbook["rules"]
                    ],
                    "approved_examples": [
                        {
                            "scenario": row.get("scenario"),
                            "stage": row.get("stage"),
                            "intended_act": row.get("intended_act"),
                            "response": str(row.get("good_response") or "")[:500],
                        }
                        for row in playbook["examples"]
                    ],
                    "callbacks": memory["callbacks"],
                    "persona": context.get("persona") or {},
                    "creator_instructions": {
                        "chat": str(context.get("chat_instructions") or "")[:20_000],
                        "brand": str(context.get("brand_bible") or "")[:12_000],
                    },
                    "diversity_context": {
                        "recent_fan": recent_fan_messages,
                        "recent_creator": global_creator_messages[-100:],
                    },
                }
            )
            prompt_fingerprint = compiled.fingerprint
            compilation_report = compiled.report
            has_memory_conflict = int(memory.get("conflicts_excluded") or 0) > 0
            context_confidence = 0.8
            if not reduction.accepted or has_memory_conflict:
                context_confidence = 0.4
            elif float(proposal.uncertainty or 0.0) >= 0.75:
                context_confidence = 0.5
            route = self.router.route(
                fan_message=str(context.get("fan_message") or ""),
                trigger_kind=trigger_kind,
                history=str(context.get("history") or ""),
                has_memory_conflict=has_memory_conflict,
                failed_tactic_count=len(state.get("recent_failed_acts") or []),
                context_confidence=context_confidence,
            )
            result = self.planner.generate(
                compiled,
                strategic=route.path == "strategic",
                recent_fan_messages=recent_fan_messages,
                recent_creator_messages=recent_creator_messages,
                creator_wide_messages=(
                    global_creator_messages
                    if self.settings.global_diversity_mode == "shadow"
                    else []
                ),
            )
            # A shadow draft is evidence, not a delivered callback. Callback
            # cooldowns may only advance after a future authorized send is
            # confirmed, so shadow evaluation cannot influence live behavior.
            candidate_fingerprints = [
                self.planner.diversity.evaluate(
                    item.message,
                    recent_fan_messages=recent_fan_messages,
                    recent_creator_messages=recent_creator_messages,
                    creator_wide_messages=(
                        global_creator_messages
                        if self.settings.global_diversity_mode == "shadow"
                        else []
                    ),
                    primary_act=item.act,
                    secondary_act=result.plan.strategy.secondary_act,
                ).fingerprint
                for item in result.plan.candidates
            ]
            selected_fingerprint = (
                hashlib.sha256(result.selected_message.encode("utf-8")).hexdigest()
                if result.selected_message
                else None
            )
            self.intelligence.record_run(
                {
                    "fan_id": fan_id,
                    "inbound_message_id": inbound_id,
                    "current_decision_id": current_decision_id,
                    "status": (
                        "complete"
                        if result.selection_mode == "model_candidate"
                        else "grounded_fallback"
                        if result.selection_mode == "grounded_fallback"
                        else "operator_review_required"
                    ),
                    "shadow": True,
                    "versions": {
                        "pipeline": "conversation-intelligence-v3.1",
                        "playbook": playbook["fingerprint"],
                    },
                    "prompt_fingerprint": prompt_fingerprint,
                    "compilation_report": compilation_report,
                    "understanding": {
                        "emotion": result.plan.understanding.emotion,
                        "intent": result.plan.understanding.intent,
                        "underlying_need": result.plan.understanding.underlying_need,
                        "evidence_codes": [
                            item.observation[:64]
                            for item in result.plan.understanding.evidence
                        ],
                    },
                    "relationship": result.plan.relationship.model_dump(exclude={"evidence"}),
                    "strategy": {
                        "primary_act": result.plan.strategy.primary_act,
                        "secondary_act": result.plan.strategy.secondary_act,
                        "should_ask_question": result.plan.strategy.should_ask_question,
                        "execution_path": route.path,
                        "routing_reasons": list(route.reasons),
                        "routing_risk_flags": list(route.risk_flags),
                        "memory_conflicts_excluded": int(
                            memory.get("conflicts_excluded") or 0
                        ),
                        "context_confidence": context_confidence,
                        "selection_mode": result.selection_mode,
                        "fallback_reason": result.fallback_reason,
                        "requires_operator_review": result.requires_operator_review,
                    },
                    "delivery": result.plan.delivery.model_dump(),
                    "candidate_fingerprints": candidate_fingerprints,
                    "selected_candidate_fingerprint": selected_fingerprint,
                    "rejection_codes": list(result.rejection_codes),
                    "model": self.planner.model,
                    "model_calls": result.model_calls,
                    "latency_ms": result.latency_ms,
                    "estimated_cost": result.estimated_cost,
                    "completed_at": utcnow(),
                }
            )
        except V3PlannerError as error:
            self._record_failure(
                inbound_id,
                fan_id,
                current_decision_id,
                error.code,
                prompt_fingerprint,
                compilation_report,
            )
        except Exception as error:
            logger.error(
                "Conversation Intelligence V3 shadow failure type=%s",
                type(error).__name__,
            )
            self._record_failure(
                inbound_id,
                fan_id,
                current_decision_id,
                "internal_error",
                prompt_fingerprint,
                compilation_report,
            )

    def _record_failure(
        self,
        inbound_id: int,
        fan_id: str,
        current_decision_id: int | None,
        status: str,
        prompt_fingerprint: str,
        compilation_report: dict,
    ) -> None:
        self.intelligence.record_run(
            {
                "fan_id": fan_id,
                "inbound_message_id": inbound_id,
                "current_decision_id": current_decision_id,
                "status": str(status)[:24],
                "shadow": True,
                "versions": {"pipeline": "conversation-intelligence-v3.1"},
                "prompt_fingerprint": prompt_fingerprint,
                "compilation_report": compilation_report,
                "understanding": {},
                "relationship": {},
                "strategy": {},
                "delivery": {},
                "candidate_fingerprints": [],
                "rejection_codes": [str(status)[:64]],
                "model": self.planner.model,
                "model_calls": 0,
                "latency_ms": 0,
                "estimated_cost": 0.0,
                "completed_at": utcnow(),
            }
        )

    def _discard(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)

    def wait_for_idle(self) -> None:
        with self._lock:
            futures = tuple(self._futures)
        if futures:
            wait(futures)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def safe_status(self) -> dict:
        return {
            **self.settings.safe_status(),
            "creator_id": self.creator_id,
            "shadow_percent": self.shadow_percent,
            "outbox_write_capability": False,
            "provider_write_capability": False,
            "model": self.planner.model,
        }
