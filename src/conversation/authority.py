"""Deterministic, deployment-bounded authority selection for Brain 2.0."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from src.conversation.brain2 import BrainRuntimeSettings


@dataclass(frozen=True)
class BrainAuthoritySelection:
    authority: str
    reason: str
    bucket: int | None = None
    requested_percent: int = 0
    experiment_id: str | None = None


class BrainAuthorityRouter:
    """Choose authority without side effects or access to delivery APIs."""

    def select(
        self,
        *,
        settings: BrainRuntimeSettings,
        creator_id: str,
        fan_id: str,
        experiment_id: str | None = None,
    ) -> BrainAuthoritySelection:
        requested = int(settings.live_percent)
        common = {
            "requested_percent": requested,
            "experiment_id": experiment_id,
        }
        if settings.mode != "advanced":
            return BrainAuthoritySelection(
                authority="current",
                reason=f"mode_{settings.mode}",
                **common,
            )
        if not settings.allow_advanced_send:
            return BrainAuthoritySelection(
                authority="current",
                reason="deployment_guard_blocked",
                **common,
            )
        if requested <= 0:
            return BrainAuthoritySelection(
                authority="current",
                reason="live_percent_zero",
                **common,
            )
        if requested > int(settings.max_live_percent):
            return BrainAuthoritySelection(
                authority="current",
                reason="deployment_ceiling_exceeded",
                **common,
            )
        digest = hashlib.sha256(
            (
                f"{creator_id}:{fan_id}:{settings.version}:"
                f"{experiment_id or 'default'}:advanced"
            ).encode("utf-8")
        ).digest()
        bucket = int.from_bytes(digest[:8], "big") % 10_000
        authority = "advanced" if bucket < requested * 100 else "current"
        return BrainAuthoritySelection(
            authority=authority,
            reason=("sticky_assignment" if authority == "advanced" else "control_assignment"),
            bucket=bucket,
            **common,
        )


class AutomaticRollbackEvaluator:
    """Evaluate bounded advanced-attempt telemetry without delivery side effects."""

    SAFETY_CODES = frozenset(
        {
            "sales_or_ppv",
            "online_tracking",
            "media_promise",
            "prompt_injection_echo",
            "invented_real_world_activity",
            "hard_boundary_conflict",
        }
    )

    def __init__(
        self,
        minimum_rate_window: int = 100,
        minimum_outcome_window: int = 50,
    ):
        self.minimum_rate_window = max(20, int(minimum_rate_window))
        self.minimum_outcome_window = max(20, int(minimum_outcome_window))

    def evaluate(
        self,
        attempts: list[dict],
        *,
        outcomes: dict | None = None,
        operational: dict | None = None,
    ) -> str | None:
        operational = operational or {}
        if operational.get("kill_switch_requested"):
            return "operator_kill_switch"
        for field, reason in (
            ("duplicate_outbox_writes", "advanced_duplicate_outbox_write"),
            ("unauthorized_outbox_writes", "advanced_unauthorized_outbox_write"),
            ("database_failures", "advanced_database_failure"),
            ("persistence_failures", "advanced_persistence_failure"),
            ("state_consistency_failures", "advanced_state_consistency_failure"),
        ):
            if int(operational.get(field) or 0) > 0:
                return reason
        advanced = [
            item
            for item in attempts
            if item.get("authority") == "advanced" or item.get("fallback_used")
        ]
        for item in advanced:
            gate = item.get("gate_results") or {}
            codes = set(gate.get("reason_codes") or ())
            violation = next(iter(codes & self.SAFETY_CODES), None)
            if violation:
                return f"advanced_safety_violation:{violation}"
        outcome_reason = self._outcome_regression(outcomes or {})
        if outcome_reason:
            return outcome_reason
        if len(advanced) < self.minimum_rate_window:
            return None
        window = advanced[: self.minimum_rate_window]
        failures = [item for item in window if item.get("fallback_used")]
        if len(failures) / len(window) > 0.01:
            return "advanced_failure_rate"
        json_failures = [
            item
            for item in failures
            if any(
                marker in str(item.get("fallback_reason") or "")
                for marker in ("_json_invalid", "_schema_invalid", "_output_empty", "output_truncated")
            )
        ]
        if len(json_failures) / len(window) > 0.005:
            return "advanced_json_schema_rate"
        provider_transient = [
            item
            for item in failures
            if item.get("fallback_reason")
            in {"provider_timeout", "provider_rate_limited"}
        ]
        if len(provider_transient) / len(window) > 0.02:
            return "advanced_provider_transient_rate"
        for route, ceiling in (("fast", 8000), ("strategic", 20000)):
            latencies = sorted(
                int(item.get("latency_ms") or 0)
                for item in window
                if item.get("route") == route
            )
            if not latencies:
                continue
            index = max(0, min(len(latencies) - 1, -(-95 * len(latencies) // 100) - 1))
            if latencies[index] > ceiling:
                return f"advanced_{route}_latency_p95"
        return None

    def _outcome_regression(self, outcomes: dict) -> str | None:
        advanced = outcomes.get("advanced") or {}
        control = outcomes.get("control") or {}
        advanced_attempts = int(advanced.get("attempts") or 0)
        control_attempts = int(control.get("attempts") or 0)
        if min(advanced_attempts, control_attempts) < self.minimum_outcome_window:
            return None

        def rate(bucket: dict, field: str, attempts: int) -> float:
            return float(bucket.get(field) or 0) / attempts

        advanced_negative = rate(advanced, "negative_signals", advanced_attempts)
        control_negative = rate(control, "negative_signals", control_attempts)
        if (
            advanced_negative >= control_negative + 0.03
            and advanced_negative >= max(0.03, control_negative * 1.5)
        ):
            return "advanced_negative_signal_regression"

        for field, reason in (
            ("meaningful_replies", "advanced_meaningful_reply_regression"),
            ("continuations", "advanced_continuation_regression"),
        ):
            advanced_rate = rate(advanced, field, advanced_attempts)
            control_rate = rate(control, field, control_attempts)
            if control_rate > 0 and advanced_rate < control_rate * 0.95:
                return reason
        return None
