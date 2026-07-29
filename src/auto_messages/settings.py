"""Validated settings for online and stalled conversation triggers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


def _bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
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


def _text(value: object, default: str = "", *, maximum: int = 4000) -> str:
    normalized = str(value if value is not None else default).strip()
    return normalized[:maximum]


@dataclass(frozen=True)
class AutoMessageTriggerSettings:
    enabled: bool
    response_mode: str
    instructions: str
    fixed_message: str
    cooldown_hours: int
    max_per_hour: int
    max_per_day: int
    max_per_fan_per_day: int
    include_currently_online: bool = False
    online_window_seconds: int = 600
    poll_interval_seconds: int = 1800
    stalled_after_hours: int = 48
    scan_interval_seconds: int = 3600
    scan_batch_size: int = 5

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
        *,
        prefix: str,
        trigger_type: str,
    ) -> "AutoMessageTriggerSettings":
        response_mode = _text(
            values.get(f"{prefix}_RESPONSE_MODE"),
            "ai_contextual",
            maximum=32,
        ).lower()
        if response_mode not in {"ai_contextual", "fixed"}:
            response_mode = "ai_contextual"
        online = trigger_type == "online"
        return cls(
            enabled=_bool(values.get(f"{prefix}_ENABLED")),
            response_mode=response_mode,
            instructions=_text(
                values.get(f"{prefix}_INSTRUCTIONS"),
                (
                    "Start a natural, low-pressure conversation based on the "
                    "fan's history. Do not sell, mention PPV, or promise media."
                    if online
                    else
                    "Reopen the conversation naturally using the last shared "
                    "context. Do not guilt the fan or repeat the last message."
                ),
            ),
            fixed_message=_text(
                values.get(f"{prefix}_FIXED_MESSAGE"),
                "",
                maximum=500,
            ),
            cooldown_hours=_int(
                values.get(f"{prefix}_COOLDOWN_HOURS"),
                72 if online else 168,
                minimum=1,
                maximum=24 * 90,
            ),
            max_per_hour=_int(
                values.get(f"{prefix}_MAX_PER_HOUR"),
                0,
                minimum=0,
                maximum=100,
            ),
            max_per_day=_int(
                values.get(f"{prefix}_MAX_PER_DAY"),
                0,
                minimum=0,
                maximum=1000,
            ),
            max_per_fan_per_day=_int(
                values.get(f"{prefix}_MAX_PER_FAN_PER_DAY"),
                0,
                minimum=0,
                maximum=3,
            ),
            include_currently_online=_bool(
                values.get(f"{prefix}_INCLUDE_CURRENTLY_ONLINE")
            ),
            online_window_seconds=_int(
                values.get(f"{prefix}_ONLINE_WINDOW_SECONDS"),
                600,
                minimum=60,
                maximum=3600,
            ),
            poll_interval_seconds=_int(
                values.get(f"{prefix}_POLL_INTERVAL_SECONDS"),
                1800,
                minimum=300,
                maximum=86400,
            ),
            stalled_after_hours=_int(
                values.get(f"{prefix}_STALLED_AFTER_HOURS"),
                48,
                minimum=6,
                maximum=24 * 365,
            ),
            scan_interval_seconds=_int(
                values.get(f"{prefix}_SCAN_INTERVAL_SECONDS"),
                3600,
                minimum=300,
                maximum=86400,
            ),
            scan_batch_size=_int(
                values.get(f"{prefix}_SCAN_BATCH_SIZE"),
                5,
                minimum=1,
                maximum=500,
            ),
        )

    def safe_status(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AutoMessagesSettings:
    online: AutoMessageTriggerSettings
    stalled: AutoMessageTriggerSettings

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
    ) -> "AutoMessagesSettings":
        return cls(
            online=AutoMessageTriggerSettings.from_mapping(
                values,
                prefix="AUTO_MESSAGES_ONLINE",
                trigger_type="online",
            ),
            stalled=AutoMessageTriggerSettings.from_mapping(
                values,
                prefix="AUTO_MESSAGES_STALLED",
                trigger_type="stalled",
            ),
        )

    def safe_status(self) -> dict:
        return {
            "online": self.online.safe_status(),
            "stalled": self.stalled.safe_status(),
        }
