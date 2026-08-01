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
        return bool(self.allow_live_send and self.has_live_component)

    def safe_status(self) -> dict:
        return {
            **asdict(self),
            "any_shadow": self.any_shadow,
            "has_live_component": self.has_live_component,
            "live_send_authority": self.live_send_authority,
            "outbox_write_capability": False,
        }
