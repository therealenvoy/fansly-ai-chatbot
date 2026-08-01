"""Independent deployment ceilings for Conversation Intelligence V3."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


MODE_RANK = {"off": 0, "shadow": 1, "live": 2}
OUTCOME_RANK = {"off": 0, "observe": 1}


def _mode(value: object, *, outcome: bool = False) -> str:
    allowed = OUTCOME_RANK if outcome else MODE_RANK
    normalized = str(value or "off").strip().lower()
    return normalized if normalized in allowed else "off"


def _effective(requested: str, ceiling: str, *, outcome: bool = False) -> str:
    rank = OUTCOME_RANK if outcome else MODE_RANK
    maximum = min(rank[requested], rank[ceiling])
    return next(name for name, value in rank.items() if value == maximum)


def _percent(value: object, default: int = 0) -> int:
    try:
        return max(0, min(int(value), 100))
    except (TypeError, ValueError):
        return max(0, min(int(default), 100))


def _money(value: object, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1_000.0))
    except (TypeError, ValueError):
        return max(0.0, min(float(default), 1_000.0))


@dataclass(frozen=True)
class V3RuntimeSettings:
    """Effective V3 authority; environment ceilings always win."""

    playbook_engine_mode: str = "off"
    relationship_state_v2_mode: str = "off"
    memory_retrieval_v3_mode: str = "off"
    strategy_planner_v2_mode: str = "off"
    global_diversity_mode: str = "off"
    outcome_learning_mode: str = "off"
    multi_bubble_mode: str = "off"
    allow_live_send: bool = False
    live_percent: int = 0
    max_live_percent: int = 0
    max_daily_cost: float = 0.0

    @classmethod
    def from_mappings(
        cls,
        environment: Mapping[str, object],
        requested: Mapping[str, object] | None = None,
    ) -> "V3RuntimeSettings":
        requested = requested or {}

        def resolved(key: str, *, outcome: bool = False) -> str:
            ceiling = _mode(environment.get(key), outcome=outcome)
            request = _mode(requested.get(key, ceiling), outcome=outcome)
            return _effective(request, ceiling, outcome=outcome)

        allow_send = str(
            environment.get("CONVERSATION_INTELLIGENCE_V3_ALLOW_SEND", "false")
        ).strip().lower() in {"1", "true", "yes", "on"}
        maximum_live = _percent(
            environment.get(
                "CONVERSATION_INTELLIGENCE_V3_MAX_LIVE_PERCENT",
                "0",
            )
        )
        requested_live = _percent(
            requested.get(
                "CONVERSATION_INTELLIGENCE_V3_LIVE_PERCENT",
                environment.get(
                    "CONVERSATION_INTELLIGENCE_V3_LIVE_PERCENT",
                    "0",
                ),
            )
        )
        maximum_daily_cost = _money(
            environment.get(
                "CONVERSATION_INTELLIGENCE_V3_MAX_DAILY_COST",
                "0",
            )
        )
        return cls(
            playbook_engine_mode=resolved("PLAYBOOK_ENGINE_MODE"),
            relationship_state_v2_mode=resolved("RELATIONSHIP_STATE_V2_MODE"),
            memory_retrieval_v3_mode=resolved("MEMORY_RETRIEVAL_V3_MODE"),
            strategy_planner_v2_mode=resolved("STRATEGY_PLANNER_V2_MODE"),
            global_diversity_mode=resolved("GLOBAL_DIVERSITY_MODE"),
            outcome_learning_mode=resolved(
                "OUTCOME_LEARNING_MODE",
                outcome=True,
            ),
            multi_bubble_mode=resolved("MULTI_BUBBLE_MODE"),
            allow_live_send=allow_send,
            live_percent=min(requested_live, maximum_live),
            max_live_percent=maximum_live,
            max_daily_cost=maximum_daily_cost,
        )

    @property
    def any_shadow(self) -> bool:
        return any(
            value == "shadow"
            for key, value in asdict(self).items()
            if key.endswith("_mode")
        )

    @property
    def has_live_component(self) -> bool:
        return any(
            value == "live"
            for key, value in asdict(self).items()
            if key.endswith("_mode")
        )

    @property
    def live_send_authority(self) -> bool:
        core_modes = (
            self.playbook_engine_mode,
            self.relationship_state_v2_mode,
            self.memory_retrieval_v3_mode,
            self.strategy_planner_v2_mode,
            self.global_diversity_mode,
        )
        return bool(
            self.allow_live_send
            and self.live_percent > 0
            and self.max_daily_cost > 0
            and all(mode == "live" for mode in core_modes)
        )

    def safe_status(self) -> dict:
        return {
            **asdict(self),
            "any_shadow": self.any_shadow,
            "has_live_component": self.has_live_component,
            "live_send_authority": self.live_send_authority,
            "outbox_write_capability": False,
        }
