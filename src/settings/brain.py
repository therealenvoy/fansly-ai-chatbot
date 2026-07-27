"""Validated creator-scoped Brain 2.0 runtime controls."""

from __future__ import annotations

from typing import Mapping

from src.conversation.brain2 import BrainRuntimeSettings
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

    def snapshot(self) -> BrainRuntimeSettings:
        values = dict(self.environment)
        for _, (database_key, environment_key) in _FIELDS.items():
            stored = self.settings_store.get_scoped(database_key)
            if stored is not None:
                values[environment_key] = stored
        return BrainRuntimeSettings.from_mapping(values)

    def save(self, updates: dict) -> BrainRuntimeSettings:
        if not isinstance(updates, dict):
            raise BrainSettingsError("brain settings must be a JSON object")
        unknown = set(updates) - set(_FIELDS)
        if unknown:
            raise BrainSettingsError(
                f"unknown brain setting: {sorted(unknown)[0]}"
            )
        current = self.snapshot()
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
        if mode == "advanced" and not allow_advanced:
            raise BrainSettingsError(
                "advanced live authority is disabled by the deployment guard"
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
        environment_values = {
            environment_key: merged[field]
            for field, (_, environment_key) in _FIELDS.items()
        }
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
        self.settings_store.set_many(database_values)
        if self.shadow_runtime is not None:
            self.shadow_runtime.update_settings(validated)
        return validated
