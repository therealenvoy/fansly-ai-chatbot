"""Fail-closed deployment controls for the Human Delivery layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(
    value: object,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _float(
    value: object,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


@dataclass(frozen=True)
class HumanDeliverySettings:
    """Deployment ceilings always win over future database requests."""

    enabled: bool = False
    mode: str = "off"
    shadow_percent: int = 0
    live_percent: int = 0
    max_live_percent: int = 0
    allow_multi_bubble_send: bool = False
    max_bubbles: int = 3
    average_bubble_budget: float = 1.35
    turn_debounce_seconds: int = 4
    turn_max_window_seconds: int = 12
    casing_mode: str = "mostly_lowercase"
    allow_typos: bool = False
    prompt_compiler_enabled: bool = False
    memory_v2_enabled: bool = False
    advanced_candidates_enabled: bool = False

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
    ) -> "HumanDeliverySettings":
        mode = str(values.get("HUMAN_DELIVERY_MODE", "off")).strip().lower()
        if mode not in {"off", "shadow", "live"}:
            mode = "off"
        ceiling = _int(
            values.get("HUMAN_DELIVERY_MAX_LIVE_PERCENT"),
            0,
            minimum=0,
            maximum=100,
        )
        requested_live = _int(
            values.get("HUMAN_DELIVERY_LIVE_PERCENT"),
            0,
            minimum=0,
            maximum=100,
        )
        casing_mode = str(
            values.get(
                "HUMAN_DELIVERY_CASING_MODE",
                "mostly_lowercase",
            )
        ).strip().lower()
        if casing_mode not in {
            "standard",
            "mostly_lowercase",
            "mirror_fan",
            "high_energy",
            "serious",
        }:
            casing_mode = "mostly_lowercase"
        enabled = _bool(values.get("HUMAN_DELIVERY_ENABLED"))
        allow_multi = _bool(
            values.get("HUMAN_DELIVERY_ALLOW_MULTI_BUBBLE_SEND")
        )
        return cls(
            enabled=enabled,
            mode=mode if enabled else "off",
            shadow_percent=_int(
                values.get("HUMAN_DELIVERY_SHADOW_PERCENT"),
                0,
                minimum=0,
                maximum=100,
            ),
            live_percent=(
                min(requested_live, ceiling)
                if enabled and mode == "live"
                else 0
            ),
            max_live_percent=ceiling,
            allow_multi_bubble_send=(
                bool(enabled and mode == "live" and allow_multi and ceiling > 0)
            ),
            max_bubbles=_int(
                values.get("HUMAN_DELIVERY_MAX_BUBBLES"),
                3,
                minimum=1,
                maximum=3,
            ),
            average_bubble_budget=_float(
                values.get("HUMAN_DELIVERY_AVG_BUBBLE_BUDGET"),
                1.35,
                minimum=1.0,
                maximum=3.0,
            ),
            turn_debounce_seconds=_int(
                values.get("HUMAN_DELIVERY_TURN_DEBOUNCE_SECONDS"),
                4,
                minimum=1,
                maximum=15,
            ),
            turn_max_window_seconds=_int(
                values.get("HUMAN_DELIVERY_TURN_MAX_WINDOW_SECONDS"),
                12,
                minimum=3,
                maximum=30,
            ),
            casing_mode=casing_mode,
            allow_typos=_bool(
                values.get("HUMAN_DELIVERY_ALLOW_TYPOS")
            ),
            prompt_compiler_enabled=_bool(
                values.get("HUMAN_DELIVERY_PROMPT_COMPILER")
            ),
            memory_v2_enabled=_bool(
                values.get("HUMAN_DELIVERY_MEMORY_V2")
            ),
            advanced_candidates_enabled=_bool(
                values.get("HUMAN_DELIVERY_ADVANCED_CANDIDATES")
            ),
        )

    @property
    def live_authority(self) -> bool:
        return bool(
            self.enabled
            and self.mode == "live"
            and 0 < self.live_percent <= self.max_live_percent
        )

    @property
    def shadow_authority(self) -> bool:
        return bool(
            self.enabled
            and self.mode == "shadow"
            and self.shadow_percent > 0
        )

    def safe_status(self) -> dict:
        """Return normalized controls without credentials or fan data."""
        return {
            **asdict(self),
            "live_authority": self.live_authority,
            "shadow_authority": self.shadow_authority,
        }
