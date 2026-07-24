"""Five-stage funnel state machine for PPV conversion tracking.

Tracks fans through Rapport → Tease → Offer → Handle → Close.
PPV messages are ONLY allowed from the Offer stage onward.
"""

from enum import Enum


class FunnelStage(str, Enum):
    """The five stages of the PPV funnel."""
    RAPPORT = "rapport"
    TEASE = "tease"
    OFFER = "offer"
    HANDLE = "handle"
    CLOSE = "close"


# Allowed transitions: each stage maps to the set of stages it can move to.
ALLOWED_TRANSITIONS: dict[FunnelStage, set[FunnelStage]] = {
    FunnelStage.RAPPORT: {FunnelStage.TEASE},
    FunnelStage.TEASE:   {FunnelStage.OFFER, FunnelStage.RAPPORT},
    FunnelStage.OFFER:   {FunnelStage.HANDLE, FunnelStage.TEASE},
    FunnelStage.HANDLE:  {FunnelStage.CLOSE, FunnelStage.OFFER},
    FunnelStage.CLOSE:   {FunnelStage.RAPPORT},
}

# Stages where PPV (pay-per-view) messages are permitted.
PPV_ALLOWED_STAGES: set[FunnelStage] = {
    FunnelStage.OFFER,
    FunnelStage.HANDLE,
    FunnelStage.CLOSE,
}


class FunnelStateMachine:
    """Tracks a single fan's progression through the 5-stage funnel."""

    def __init__(self) -> None:
        self._current_stage: FunnelStage = FunnelStage.RAPPORT
        self.stage_history: list[FunnelStage] = [FunnelStage.RAPPORT]
        self.messages_in_stage: int = 0

    @property
    def current_stage(self) -> FunnelStage:
        """The funnel's current stage."""
        return self._current_stage

    def transition(self, to_stage: FunnelStage) -> None:
        """Move to *to_stage* if the transition is allowed.

        Raises:
            ValueError: if the transition is not in ALLOWED_TRANSITIONS.
        """
        allowed = ALLOWED_TRANSITIONS.get(self._current_stage, set())
        if to_stage not in allowed:
            raise ValueError(
                f"Cannot transition from {self._current_stage.value} "
                f"to {to_stage.value}"
            )
        self._current_stage = to_stage
        self.stage_history.append(to_stage)
        self.messages_in_stage = 0  # reset counter for new stage

    def can_send_ppv(self) -> bool:
        """Return True if PPV messages are allowed in the current stage."""
        return self._current_stage in PPV_ALLOWED_STAGES

    def min_messages_before_tease(self) -> int:
        """Return the number of rapport messages still needed before teasing.

        Only meaningful when the funnel is in RAPPORT; returns 0 otherwise.
        Requires at least 2 rapport messages before advancing to TEASE.
        """
        if self._current_stage != FunnelStage.RAPPORT:
            return 0
        return max(0, 2 - self.messages_in_stage)