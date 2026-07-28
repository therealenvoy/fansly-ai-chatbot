"""Synchronous Brain 2.0 decision service with no delivery capability."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import time

from src.conversation.brain import ConversationDecision, OBJECTIVES, TACTICS
from src.conversation.brain2 import BrainRouter, BrainRuntimeSettings, ConversationQualityGate
from src.conversation.brain2_repository import (
    BrainCostCapRepository,
    StrategicUsageCapRepository,
)
from src.conversation.shadow import ProviderContractError


@dataclass(frozen=True)
class AdvancedDecisionOutcome:
    decision: ConversationDecision | None
    succeeded: bool
    route: str
    model: str
    provider_attempts: int = 0
    model_calls: int = 0
    retry_calls: int = 0
    repair_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: int = 0
    fallback_reason: str | None = None
    gate_reason_codes: tuple[str, ...] = ()


class AdvancedBrainDecisionService:
    """Generate a typed decision; never call Fansly or write to the outbox."""

    def __init__(
        self,
        *,
        engine,
        creator_id: str,
        analyzer,
        settings_provider,
        max_workers: int = 2,
    ):
        self.creator_id = creator_id
        self.analyzer = analyzer
        self.settings_provider = settings_provider
        self.usage_caps = StrategicUsageCapRepository(engine)
        self.cost_caps = BrainCostCapRepository(engine)
        self.gate = ConversationQualityGate()
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 4)),
            thread_name_prefix="brain-advanced",
        )

    def decide(
        self,
        *,
        fan_id: str,
        trigger_kind: str,
        context: dict,
    ) -> AdvancedDecisionOutcome:
        started = time.monotonic()
        settings = self.settings_provider()
        router = BrainRouter(settings.strategic_complexity_threshold)
        route = router.route(
            fan_message=str(context.get("fan_message") or ""),
            trigger_kind=trigger_kind,
            history=str(context.get("history") or ""),
            has_memory_conflict=bool(context.get("has_memory_conflict")),
            failed_tactic_count=int(context.get("failed_tactic_count") or 0),
            context_confidence=float(context.get("context_confidence") or 1.0),
        ).path
        execution_route = (
            "fast"
            if route == "strategic" and settings.max_model_calls_per_turn < 3
            else route
        )
        immutable_context = dict(context)
        immutable_context["trigger_kind"] = trigger_kind
        immutable_context["_max_provider_attempts_per_turn"] = (
            settings.max_model_calls_per_turn
        )
        immutable_context["_json_repair_attempts"] = settings.json_repair_attempts
        if getattr(self.analyzer, "supports_attempt_reservation", False):
            def reserve_attempt(maximum_cost: float):
                if not self.usage_caps.reserve(
                    creator_id=self.creator_id,
                    calls=1,
                    hourly_limit=settings.max_strategic_calls_per_hour,
                    daily_limit=settings.max_strategic_calls_per_day,
                ):
                    return "strategic_call_cap"
                if not self.cost_caps.reserve(
                    creator_id=self.creator_id,
                    estimated_cost=maximum_cost,
                    daily_limit=settings.max_daily_cost,
                ):
                    return "daily_cost_cap"
                return True
            immutable_context["_provider_attempt_reserver"] = reserve_attempt
        else:
            planned_calls = 1 if execution_route == "fast" else 3
            if not self.usage_caps.reserve(
                creator_id=self.creator_id,
                calls=planned_calls,
                hourly_limit=settings.max_strategic_calls_per_hour,
                daily_limit=settings.max_strategic_calls_per_day,
            ):
                return self._failure(
                    execution_route,
                    "strategic_call_cap",
                    started,
                )
        analyze = (
            self.analyzer.analyze_fast
            if execution_route == "fast" and hasattr(self.analyzer, "analyze_fast")
            else self.analyzer.analyze
        )
        future = self._executor.submit(analyze, immutable_context)
        try:
            result = future.result(timeout=float(settings.live_timeout_seconds))
        except FutureTimeout:
            future.cancel()
            return self._failure(execution_route, "advanced_timeout", started)
        except ProviderContractError as exc:
            return self._failure(execution_route, exc.code, started)
        except Exception:
            return self._failure(
                execution_route,
                "unclassified_internal_error",
                started,
            )

        latest = self.settings_provider()
        if self._authority_signature(latest) != self._authority_signature(settings):
            return self._failure(
                execution_route,
                "stale_authority_after_rollback",
                started,
                result=result,
            )
        candidate = str(result.selected_candidate or "").strip()
        gate = self.gate.evaluate(
            candidate,
            recent_creator_messages=list(context.get("recent_creator_messages") or []),
            question_streak=int(context.get("question_streak") or 0),
            pet_name_streak=int(context.get("pet_name_streak") or 0),
            hard_boundaries=list(context.get("hard_boundaries") or []),
            max_length=500,
        )
        if not gate.approved:
            return self._failure(
                execution_route,
                "quality_gate_rejected",
                started,
                result=result,
                gate_reason_codes=gate.reason_codes,
            )
        planner = result.planner or {}
        objective = str(planner.get("objective") or "maintain").strip().lower()
        tactic = str(planner.get("tactic") or "direct_answer").strip().lower()
        if objective not in OBJECTIVES:
            objective = "reconnect" if trigger_kind in {"online", "stalled"} else "maintain"
        if tactic not in TACTICS:
            tactic = "gentle_check_in" if trigger_kind in {"online", "stalled"} else "direct_answer"
        confidence = planner.get("confidence", 0.5)
        try:
            confidence = min(max(float(confidence), 0.0), 1.0)
        except (TypeError, ValueError):
            confidence = 0.5
        decision = ConversationDecision(
            fan_state=str(planner.get("fan_state") or planner.get("fan_emotion") or "unknown")[:64],
            state_summary="Structured Brain 2.0 conversation assessment.",
            objective=objective,
            tactic=tactic,
            open_thread=(str(planner.get("open_thread") or planner.get("active_thread") or "").strip()[:500] or None),
            draft=candidate,
            critique=("structured candidate passed deterministic quality gates",),
            final_message=candidate,
            confidence=confidence,
        )
        return AdvancedDecisionOutcome(
            decision=decision,
            succeeded=True,
            route=execution_route,
            model=str(getattr(self.analyzer, "model", "unknown")),
            provider_attempts=int(result.provider_attempts),
            model_calls=int(result.model_calls),
            retry_calls=int(result.retry_calls),
            repair_calls=int(result.repair_calls),
            prompt_tokens=int(result.prompt_tokens),
            completion_tokens=int(result.completion_tokens),
            total_tokens=int(result.total_tokens),
            estimated_cost=float(result.estimated_cost),
            latency_ms=int((time.monotonic() - started) * 1_000),
        )

    def _failure(
        self,
        route: str,
        reason: str,
        started: float,
        *,
        result=None,
        gate_reason_codes=(),
    ) -> AdvancedDecisionOutcome:
        return AdvancedDecisionOutcome(
            decision=None,
            succeeded=False,
            route=route,
            model=str(getattr(self.analyzer, "model", "unknown")),
            provider_attempts=int(getattr(result, "provider_attempts", 0)),
            model_calls=int(getattr(result, "model_calls", 0)),
            retry_calls=int(getattr(result, "retry_calls", 0)),
            repair_calls=int(getattr(result, "repair_calls", 0)),
            prompt_tokens=int(getattr(result, "prompt_tokens", 0)),
            completion_tokens=int(getattr(result, "completion_tokens", 0)),
            total_tokens=int(getattr(result, "total_tokens", 0)),
            estimated_cost=float(getattr(result, "estimated_cost", 0.0)),
            latency_ms=int((time.monotonic() - started) * 1_000),
            fallback_reason=reason,
            gate_reason_codes=tuple(gate_reason_codes),
        )

    @staticmethod
    def _authority_signature(settings: BrainRuntimeSettings) -> tuple:
        return (
            settings.mode,
            settings.version,
            settings.allow_advanced_send,
            settings.live_percent,
            settings.max_live_percent,
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
