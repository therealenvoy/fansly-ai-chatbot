"""Validated creator-scoped Brain 2.0 runtime controls."""

from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from src.conversation.brain2 import BrainRuntimeSettings
from src.conversation.brain2_repository import BrainConfigurationAuditRepository
from src.engagement.control_plane import (
    Ownership,
    OwnershipConflict,
    TriggerOwner,
    TriggerOwnershipRepository,
    TriggerType,
)
from src.settings.store import SettingsStore


class BrainSettingsError(ValueError):
    pass


_FIELDS = {
    "mode": ("brain.mode", "BRAIN_MODE"),
    "version": ("brain.version", "BRAIN_VERSION"),
    "shadow_sample_percent": (
        "brain.shadow_sample_percent",
        "BRAIN_SHADOW_SAMPLE_PERCENT",
    ),
    "strategic_complexity_threshold": (
        "brain.strategic_complexity_threshold",
        "BRAIN_STRATEGIC_COMPLEXITY_THRESHOLD",
    ),
    "max_strategic_calls_per_hour": (
        "brain.max_strategic_calls_per_hour",
        "BRAIN_MAX_STRATEGIC_CALLS_PER_HOUR",
    ),
    "max_strategic_calls_per_day": (
        "brain.max_strategic_calls_per_day",
        "BRAIN_MAX_STRATEGIC_CALLS_PER_DAY",
    ),
    "max_model_calls_per_turn": (
        "brain.max_model_calls_per_turn",
        "BRAIN_MAX_MODEL_CALLS_PER_TURN",
    ),
    "max_output_tokens": (
        "brain.max_output_tokens",
        "BRAIN_MAX_OUTPUT_TOKENS",
    ),
    "json_repair_attempts": (
        "brain.json_repair_attempts",
        "BRAIN_JSON_REPAIR_ATTEMPTS",
    ),
    "outcome_window_hours": (
        "brain.outcome_window_hours",
        "BRAIN_OUTCOME_WINDOW_HOURS",
    ),
    "live_percent": ("brain.live_percent", "BRAIN_LIVE_PERCENT"),
    "auto_rollback": ("brain.auto_rollback", "BRAIN_AUTO_ROLLBACK"),
    "live_timeout_seconds": (
        "brain.live_timeout_seconds",
        "BRAIN_LIVE_TIMEOUT_SECONDS",
    ),
    "max_daily_cost": ("brain.max_daily_cost", "BRAIN_MAX_DAILY_COST"),
}


class BrainSettingsService:
    def __init__(
        self,
        *,
        settings_store: SettingsStore,
        environment: Mapping[str, object],
        shadow_runtime=None,
    ):
        self.settings_store = settings_store
        self.environment = environment
        self.shadow_runtime = shadow_runtime
        self.audit = BrainConfigurationAuditRepository(settings_store.engine)
        self.trigger_ownership = TriggerOwnershipRepository(
            settings_store.engine
        )

    def snapshot(self) -> BrainRuntimeSettings:
        values = dict(self.environment)
        for _, (database_key, environment_key) in _FIELDS.items():
            stored = self.settings_store.get_scoped(database_key)
            if stored is not None:
                values[environment_key] = stored
        return BrainRuntimeSettings.from_mapping(values)

    def save(
        self,
        updates: dict,
        *,
        actor: str = "crm",
        reason: str | None = None,
        _event_type: str = "settings_changed",
    ) -> BrainRuntimeSettings:
        if not isinstance(updates, dict):
            raise BrainSettingsError("brain settings must be a JSON object")
        unknown = set(updates) - set(_FIELDS)
        if unknown:
            raise BrainSettingsError(
                f"unknown brain setting: {sorted(unknown)[0]}"
            )
        current = self.snapshot()
        previous_values = asdict(current)
        merged = {
            field: getattr(current, field)
            for field in _FIELDS
        }
        merged.update(updates)
        mode = str(merged["mode"]).strip().lower()
        allow_advanced = (
            str(
                self.environment.get(
                    "BRAIN_ALLOW_ADVANCED_SEND",
                    "false",
                )
            ).lower()
            == "true"
        )
        try:
            requested_live = int(merged["live_percent"])
        except (TypeError, ValueError) as exc:
            raise BrainSettingsError("live_percent must be an integer") from exc
        maximum_live = int(self.environment.get("BRAIN_MAX_LIVE_PERCENT", 0))
        if requested_live < 0 or requested_live > 100:
            raise BrainSettingsError("live_percent must be between 0 and 100")
        if mode == "advanced" and not allow_advanced:
            raise BrainSettingsError(
                "advanced live authority is disabled by the deployment guard"
            )
        if requested_live > 0 and (mode != "advanced" or not allow_advanced):
            raise BrainSettingsError(
                "live_percent requires advanced mode and the deployment guard"
            )
        if requested_live > maximum_live:
            raise BrainSettingsError(
                "live_percent exceeds the deployment ceiling"
            )
        try:
            maximum_daily_cost = float(merged["max_daily_cost"])
        except (TypeError, ValueError) as exc:
            raise BrainSettingsError("max_daily_cost must be numeric") from exc
        if requested_live > 0 and maximum_daily_cost <= 0:
            raise BrainSettingsError(
                "live_percent requires a positive daily cost ceiling"
            )
        maximum_shadow = int(
            self.environment.get(
                "BRAIN_MAX_SHADOW_SAMPLE_PERCENT",
                100,
            )
        )
        try:
            requested_shadow = int(merged["shadow_sample_percent"])
        except (TypeError, ValueError) as exc:
            raise BrainSettingsError(
                "shadow_sample_percent must be an integer"
            ) from exc
        if requested_shadow > maximum_shadow:
            raise BrainSettingsError(
                "shadow_sample_percent exceeds the deployment ceiling"
            )
        environment_values = dict(self.environment)
        environment_values.update(
            {
                environment_key: merged[field]
                for field, (_, environment_key) in _FIELDS.items()
            }
        )
        validated = BrainRuntimeSettings.from_mapping(
            environment_values
        )
        if mode not in {"current", "shadow", "advanced"}:
            raise BrainSettingsError("mode must be current, shadow, or advanced")
        if int(merged["max_model_calls_per_turn"]) != (
            validated.max_model_calls_per_turn
        ):
            raise BrainSettingsError(
                "max_model_calls_per_turn must be between 1 and 4"
            )
        if int(merged["json_repair_attempts"]) != (
            validated.json_repair_attempts
        ):
            raise BrainSettingsError(
                "json_repair_attempts must be zero or one"
            )
        database_values = {
            _FIELDS[field][0]: str(getattr(validated, field))
            for field in _FIELDS
        }
        desired_owner = self._desired_inbound_reply_owner(validated)
        try:
            with self.settings_store.engine.begin() as connection:
                self.settings_store.set_many(
                    database_values,
                    connection=connection,
                )
                self.trigger_ownership.handoff(
                    self.settings_store.creator_id,
                    TriggerType.INBOUND_REPLY,
                    desired_owner,
                    actor=str(actor)[:64],
                    reason=(
                        str(reason)[:128]
                        if reason
                        else "Brain live authority settings changed"
                    ),
                    allowed_previous_owners=frozenset(
                        {
                            TriggerOwner.CURRENT_BRAIN,
                            TriggerOwner.BRAIN2,
                        }
                    ),
                    preserve_unlisted=(
                        desired_owner == TriggerOwner.CURRENT_BRAIN
                    ),
                    connection=connection,
                )
        except OwnershipConflict as exc:
            raise BrainSettingsError(str(exc)) from exc
        if self.shadow_runtime is not None:
            self.shadow_runtime.update_settings(validated)
        self.audit.record(
            creator_id=self.settings_store.creator_id,
            event_type=_event_type,
            actor=str(actor)[:64],
            previous_values=previous_values,
            new_values=asdict(validated),
            reason=(str(reason)[:256] if reason else None),
        )
        return validated

    def reconcile_trigger_ownership(
        self,
        *,
        actor: str = "system",
        reason: str = "startup Brain authority reconciliation",
    ) -> Ownership:
        """Align reply ownership with durable Brain authority, fail closed.

        A disabled or native/external safety owner is preserved at startup.
        Explicit live promotion through ``save`` still refuses that conflict.
        """
        settings = self.snapshot()
        desired_owner = self._desired_inbound_reply_owner(settings)
        return self.trigger_ownership.handoff(
            self.settings_store.creator_id,
            TriggerType.INBOUND_REPLY,
            desired_owner,
            actor=str(actor)[:64],
            reason=str(reason)[:128],
            allowed_previous_owners=frozenset(
                {
                    TriggerOwner.CURRENT_BRAIN,
                    TriggerOwner.BRAIN2,
                }
            ),
            preserve_unlisted=True,
        )

    @staticmethod
    def _desired_inbound_reply_owner(
        settings: BrainRuntimeSettings,
    ) -> TriggerOwner:
        if settings.mode == "advanced" and settings.live_percent > 0:
            return TriggerOwner.BRAIN2
        return TriggerOwner.CURRENT_BRAIN

    def rollback(
        self,
        *,
        actor: str = "crm",
        reason: str = "manual rollback",
    ) -> BrainRuntimeSettings:
        return self.save(
            {"mode": "current", "live_percent": 0},
            actor=actor,
            reason=reason,
            _event_type="rollback",
        )
