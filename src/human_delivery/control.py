"""Creator-scoped controls bounded by immutable deployment ceilings."""

from __future__ import annotations

from dataclasses import asdict
from typing import Mapping

from src.human_delivery.settings import HumanDeliverySettings
from src.settings.store import SettingsStore


class HumanDeliveryControlError(ValueError):
    pass


_FIELDS = {
    "enabled": ("human_delivery.enabled", "HUMAN_DELIVERY_ENABLED"),
    "mode": ("human_delivery.mode", "HUMAN_DELIVERY_MODE"),
    "shadow_percent": (
        "human_delivery.shadow_percent",
        "HUMAN_DELIVERY_SHADOW_PERCENT",
    ),
    "live_percent": (
        "human_delivery.live_percent",
        "HUMAN_DELIVERY_LIVE_PERCENT",
    ),
    "allow_multi_bubble_send": (
        "human_delivery.allow_multi_bubble_send",
        "HUMAN_DELIVERY_ALLOW_MULTI_BUBBLE_SEND",
    ),
    "max_bubbles": (
        "human_delivery.max_bubbles",
        "HUMAN_DELIVERY_MAX_BUBBLES",
    ),
    "average_bubble_budget": (
        "human_delivery.average_bubble_budget",
        "HUMAN_DELIVERY_AVG_BUBBLE_BUDGET",
    ),
    "turn_debounce_seconds": (
        "human_delivery.turn_debounce_seconds",
        "HUMAN_DELIVERY_TURN_DEBOUNCE_SECONDS",
    ),
    "turn_max_window_seconds": (
        "human_delivery.turn_max_window_seconds",
        "HUMAN_DELIVERY_TURN_MAX_WINDOW_SECONDS",
    ),
    "casing_mode": (
        "human_delivery.casing_mode",
        "HUMAN_DELIVERY_CASING_MODE",
    ),
    "allow_typos": (
        "human_delivery.allow_typos",
        "HUMAN_DELIVERY_ALLOW_TYPOS",
    ),
    "prompt_compiler_enabled": (
        "human_delivery.prompt_compiler_enabled",
        "HUMAN_DELIVERY_PROMPT_COMPILER",
    ),
    "memory_v2_enabled": (
        "human_delivery.memory_v2_enabled",
        "HUMAN_DELIVERY_MEMORY_V2",
    ),
    "advanced_candidates_enabled": (
        "human_delivery.advanced_candidates_enabled",
        "HUMAN_DELIVERY_ADVANCED_CANDIDATES",
    ),
}


class HumanDeliveryControlService:
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
        self.deployment = HumanDeliverySettings.from_mapping(
            self.environment
        )

    def snapshot(self) -> HumanDeliverySettings:
        values = dict(self.environment)
        for _, (database_key, environment_key) in _FIELDS.items():
            stored = self.settings_store.get_scoped(database_key)
            if stored is not None:
                values[environment_key] = stored
        requested = HumanDeliverySettings.from_mapping(values)
        deployment = self.deployment
        bounded_values = {
            "HUMAN_DELIVERY_ENABLED": (
                deployment.enabled and requested.enabled
            ),
            "HUMAN_DELIVERY_MODE": requested.mode,
            "HUMAN_DELIVERY_SHADOW_PERCENT": min(
                requested.shadow_percent,
                deployment.shadow_percent,
            ),
            "HUMAN_DELIVERY_LIVE_PERCENT": min(
                requested.live_percent,
                deployment.max_live_percent,
            ),
            "HUMAN_DELIVERY_MAX_LIVE_PERCENT": (
                deployment.max_live_percent
            ),
            "HUMAN_DELIVERY_ALLOW_MULTI_BUBBLE_SEND": (
                deployment.allow_multi_bubble_send
                and requested.allow_multi_bubble_send
            ),
            "HUMAN_DELIVERY_MAX_BUBBLES": min(
                requested.max_bubbles,
                deployment.max_bubbles,
            ),
            "HUMAN_DELIVERY_AVG_BUBBLE_BUDGET": min(
                requested.average_bubble_budget,
                deployment.average_bubble_budget,
            ),
            "HUMAN_DELIVERY_TURN_DEBOUNCE_SECONDS": (
                requested.turn_debounce_seconds
            ),
            "HUMAN_DELIVERY_TURN_MAX_WINDOW_SECONDS": (
                requested.turn_max_window_seconds
            ),
            "HUMAN_DELIVERY_CASING_MODE": requested.casing_mode,
            "HUMAN_DELIVERY_ALLOW_TYPOS": (
                deployment.allow_typos and requested.allow_typos
            ),
            "HUMAN_DELIVERY_PROMPT_COMPILER": (
                deployment.prompt_compiler_enabled
                and requested.prompt_compiler_enabled
            ),
            "HUMAN_DELIVERY_MEMORY_V2": (
                deployment.memory_v2_enabled
                and requested.memory_v2_enabled
            ),
            "HUMAN_DELIVERY_ADVANCED_CANDIDATES": (
                deployment.advanced_candidates_enabled
                and requested.advanced_candidates_enabled
            ),
        }
        return HumanDeliverySettings.from_mapping(bounded_values)

    def save(self, updates: dict) -> HumanDeliverySettings:
        if not isinstance(updates, dict):
            raise HumanDeliveryControlError(
                "Human Delivery settings must be an object"
            )
        unknown = set(updates) - set(_FIELDS)
        if unknown:
            raise HumanDeliveryControlError(
                f"unknown Human Delivery setting: {sorted(unknown)[0]}"
            )
        current = self.snapshot()
        merged = {
            field: getattr(current, field)
            for field in _FIELDS
        }
        merged.update(updates)
        if bool(merged["enabled"]) and not self.deployment.enabled:
            raise HumanDeliveryControlError(
                "Human Delivery is disabled by the deployment guard"
            )
        if int(merged["shadow_percent"]) > self.deployment.shadow_percent:
            raise HumanDeliveryControlError(
                "shadow_percent exceeds the deployment ceiling"
            )
        if int(merged["live_percent"]) > self.deployment.max_live_percent:
            raise HumanDeliveryControlError(
                "live_percent exceeds the deployment ceiling"
            )
        if bool(merged["allow_multi_bubble_send"]) and not (
            self.deployment.allow_multi_bubble_send
        ):
            raise HumanDeliveryControlError(
                "multi-bubble send is disabled by the deployment guard"
            )
        for field in (
            "allow_typos",
            "prompt_compiler_enabled",
            "memory_v2_enabled",
            "advanced_candidates_enabled",
        ):
            if bool(merged[field]) and not bool(
                getattr(self.deployment, field)
            ):
                raise HumanDeliveryControlError(
                    f"{field} is disabled by the deployment guard"
                )
        values = {
            _FIELDS[field][0]: str(merged[field])
            for field in _FIELDS
        }
        self.settings_store.set_many(values)
        settings = self.snapshot()
        if self.runtime is not None:
            self.runtime.update_settings(settings)
        return settings

    def safe_status(self) -> dict:
        return {
            "effective": asdict(self.snapshot()),
            "deployment": asdict(self.deployment),
        }
