"""Creator-scoped Auto Messages controls bounded by deployment switches."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from src.settings.store import SettingsStore

from .settings import AutoMessageTriggerSettings, AutoMessagesSettings


class AutoMessagesControlError(ValueError):
    pass


_TRIGGER_FIELDS = (
    "enabled",
    "response_mode",
    "instructions",
    "fixed_message",
    "cooldown_hours",
    "max_per_hour",
    "max_per_day",
    "max_per_fan_per_day",
    "include_currently_online",
    "online_window_seconds",
    "poll_interval_seconds",
    "stalled_after_hours",
    "scan_interval_seconds",
    "scan_batch_size",
)

_LEGACY_ENVIRONMENT = {
    ("online", "enabled"): "ENABLE_ONLINE_OUTREACH",
    ("online", "include_currently_online"): "OUTREACH_EXISTING_ONLINE",
    ("online", "online_window_seconds"): "ONLINE_WINDOW_SECONDS",
    ("online", "poll_interval_seconds"): "PRESENCE_POLL_INTERVAL",
    ("online", "cooldown_hours"): "PROACTIVE_COOLDOWN_HOURS",
    ("online", "max_per_hour"): "MAX_PROACTIVE_PER_HOUR",
    ("online", "max_per_day"): "MAX_PROACTIVE_PER_DAY",
    ("online", "max_per_fan_per_day"): "MAX_PROACTIVE_PER_FAN_PER_DAY",
    ("stalled", "enabled"): "ENABLE_STALLED_OUTREACH",
    ("stalled", "stalled_after_hours"): "STALLED_AFTER_HOURS",
    ("stalled", "scan_interval_seconds"): "STALLED_SCAN_INTERVAL",
    ("stalled", "scan_batch_size"): "STALLED_SCAN_BATCH_SIZE",
    ("stalled", "cooldown_hours"): "PROACTIVE_COOLDOWN_HOURS",
    ("stalled", "max_per_hour"): "MAX_PROACTIVE_PER_HOUR",
    ("stalled", "max_per_day"): "MAX_PROACTIVE_PER_DAY",
    ("stalled", "max_per_fan_per_day"): "MAX_PROACTIVE_PER_FAN_PER_DAY",
}


class AutoMessagesControlService:
    """Persist requested settings while enforcing immutable deployment gates."""

    def __init__(
        self,
        *,
        settings_store: SettingsStore,
        environment: Mapping[str, object],
        runtime=None,
    ):
        self.settings_store = settings_store
        self.environment = dict(environment)
        self.runtime = runtime
        self.deployment_online_allowed = self._env_bool(
            self.environment.get("ENABLE_ONLINE_OUTREACH")
        )
        self.deployment_stalled_allowed = self._env_bool(
            self.environment.get("ENABLE_STALLED_OUTREACH")
        )

    @staticmethod
    def _env_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _database_key(trigger: str, field: str) -> str:
        return f"auto_messages.{trigger}.{field}"

    @staticmethod
    def _environment_key(trigger: str, field: str) -> str:
        return f"AUTO_MESSAGES_{trigger.upper()}_{field.upper()}"

    def requested(self) -> AutoMessagesSettings:
        values = dict(self.environment)
        for (trigger, field), legacy_key in _LEGACY_ENVIRONMENT.items():
            key = self._environment_key(trigger, field)
            if key not in values and legacy_key in values:
                values[key] = values[legacy_key]
        keys = [
            self._database_key(trigger, field)
            for trigger in ("online", "stalled")
            for field in _TRIGGER_FIELDS
        ]
        stored = self.settings_store.get_many_scoped(keys)
        for trigger in ("online", "stalled"):
            for field in _TRIGGER_FIELDS:
                value = stored.get(self._database_key(trigger, field))
                if value is not None:
                    values[self._environment_key(trigger, field)] = value
        return AutoMessagesSettings.from_mapping(values)

    def snapshot(self) -> AutoMessagesSettings:
        requested = self.requested()
        return AutoMessagesSettings(
            online=replace(
                requested.online,
                enabled=(
                    requested.online.enabled
                    and self.deployment_online_allowed
                ),
            ),
            stalled=replace(
                requested.stalled,
                enabled=(
                    requested.stalled.enabled
                    and self.deployment_stalled_allowed
                ),
            ),
        )

    def save(
        self,
        trigger: str,
        updates: dict,
    ) -> AutoMessagesSettings:
        if trigger not in {"online", "stalled"}:
            raise AutoMessagesControlError("unsupported trigger type")
        if not isinstance(updates, dict):
            raise AutoMessagesControlError(
                "Auto Messages settings must be an object"
            )
        unknown = set(updates) - set(_TRIGGER_FIELDS)
        if unknown:
            raise AutoMessagesControlError(
                f"unknown Auto Messages setting: {sorted(unknown)[0]}"
            )
        current = getattr(self.requested(), trigger)
        merged = {
            field: getattr(current, field)
            for field in _TRIGGER_FIELDS
        }
        merged.update(updates)
        prefix = f"AUTO_MESSAGES_{trigger.upper()}"
        normalized = AutoMessageTriggerSettings.from_mapping(
            {
                self._environment_key(trigger, field): value
                for field, value in merged.items()
            },
            prefix=prefix,
            trigger_type=trigger,
        )
        if (
            normalized.response_mode == "fixed"
            and not normalized.fixed_message
        ):
            raise AutoMessagesControlError(
                "fixed response mode requires a message"
            )
        if normalized.max_per_day < normalized.max_per_hour:
            raise AutoMessagesControlError(
                "daily limit must be at least the hourly limit"
            )
        values = {
            self._database_key(trigger, field): str(
                getattr(normalized, field)
            )
            for field in _TRIGGER_FIELDS
        }
        self.settings_store.set_many(values)
        settings = self.snapshot()
        if self.runtime is not None:
            self.runtime.update_auto_messages(settings)
        return settings

    def safe_status(self) -> dict:
        requested = self.requested()
        effective = self.snapshot()
        return {
            "requested": requested.safe_status(),
            "effective": effective.safe_status(),
            "deployment": {
                "online_allowed": self.deployment_online_allowed,
                "stalled_allowed": self.deployment_stalled_allowed,
            },
            "blocked_reasons": {
                "online": (
                    None
                    if self.deployment_online_allowed
                    else "Online outreach is disabled by the Railway deployment guard"
                ),
                "stalled": (
                    None
                    if self.deployment_stalled_allowed
                    else "Stalled outreach is disabled by the Railway deployment guard"
                ),
            },
        }
