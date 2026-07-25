"""SpiralStateMachine — perpetual escalation engine.

Replaces the linear 5-stage FunnelStateMachine with an infinite spiral:
RAPPORT → TEASE → OFFER → HANDLE → CLOSE → AFTERCARE → RAPPORT (level+1)

Key concepts:
- Phase: current position in the cycle (RAPPORT, TEASE, OFFER, HANDLE, CLOSE, AFTERCARE)
- Level: which PPV step in the sequence the fan is being sold (0 = never bought, 1+ = progressing)
- Cooldown: reduced intimacy mode after fatigue (2+ rejections)
- Warmup: faster re-rapport after ghosting
"""
from enum import Enum
from dataclasses import dataclass, field


class SpiralPhase(str, Enum):
    """Phases of the perpetual escalation cycle."""
    RAPPORT = "rapport"
    TEASE = "tease"
    OFFER = "offer"
    HANDLE = "handle"
    CLOSE = "close"
    AFTERCARE = "aftercare"


@dataclass
class EscalationLevel:
    """Tracks how many PPVs the fan has purchased (escalation depth)."""
    number: int = 0
    ppvs_bought: int = 0


# Allowed transitions between phases.
# Aftercare → RAPPORT is the loop-back that fuels the spiral.
ALLOWED_TRANSITIONS: dict[SpiralPhase, set[SpiralPhase]] = {
    SpiralPhase.RAPPORT:    {SpiralPhase.TEASE},
    SpiralPhase.TEASE:      {SpiralPhase.OFFER, SpiralPhase.RAPPORT},
    SpiralPhase.OFFER:      {SpiralPhase.HANDLE, SpiralPhase.TEASE},
    SpiralPhase.HANDLE:     {SpiralPhase.CLOSE, SpiralPhase.OFFER},
    SpiralPhase.CLOSE:      {SpiralPhase.AFTERCARE},
    SpiralPhase.AFTERCARE:  {SpiralPhase.RAPPORT},  # → back to rapport at next level
}

PPV_ALLOWED_PHASES: set[SpiralPhase] = {
    SpiralPhase.OFFER,
    SpiralPhase.HANDLE,
    SpiralPhase.CLOSE,
}


class SpiralStateMachine:
    """Tracks a single fan's position in the perpetual escalation spiral."""

    def __init__(self) -> None:
        self._phase: SpiralPhase = SpiralPhase.RAPPORT
        self.phase_history: list[SpiralPhase] = [SpiralPhase.RAPPORT]
        self.messages_in_phase: int = 0

        # Escalation
        self.level: EscalationLevel = EscalationLevel()

        # Fatigue / cooldown
        self.cooldown: bool = False
        self.consecutive_rejections: int = 0

        # Ghost warmup
        self._warmup: bool = False

    # ─── Properties ─────────────────────────────────────

    @property
    def phase(self) -> SpiralPhase:
        return self._phase

    @property
    def current_stage(self) -> SpiralPhase:
        """Alias for compatibility with existing bot code that uses .current_stage."""
        return self._phase

    @property
    def messages_in_stage(self) -> int:
        """Alias for backward compatibility."""
        return self.messages_in_phase

    @property
    def escalation_level(self) -> int:
        """The sequence step position the fan is being sold next."""
        return self.level.number + 1 if self.level.number > 0 else 1

    # ─── Transitions ────────────────────────────────────

    def transition(self, to_phase: SpiralPhase) -> None:
        """Move to *to_phase* if the transition is allowed."""
        allowed = ALLOWED_TRANSITIONS.get(self._phase, set())
        if to_phase not in allowed:
            raise ValueError(
                f"Cannot transition from {self._phase.value} to {to_phase.value}"
            )
        self._phase = to_phase
        self.phase_history.append(to_phase)
        self.messages_in_phase = 0

        # If entering RAPPORT via the aftercare loop-back, auto-exit cooldown
        if to_phase == SpiralPhase.RAPPORT and self.cooldown:
            self.exit_cooldown()

    def can_send_ppv(self) -> bool:
        """Return True if PPV is allowed in the current phase."""
        return self._phase in PPV_ALLOWED_PHASES

    def min_messages_before_tease(self) -> int:
        """Return number of rapport messages still needed before teasing.

        Normal: 2 messages minimum.
        Warmup (after ghost): 1 message minimum.
        """
        if self._phase != SpiralPhase.RAPPORT:
            return 0
        required = 1 if self._warmup else 2
        return max(0, required - self.messages_in_phase)

    def record_rapport_message(self):
        """Increment the rapport message counter."""
        self.messages_in_phase += 1

    # ─── Escalation ─────────────────────────────────────

    def advance_level(self):
        """Called when a fan purchases a PPV. Increments escalation level."""
        self.level.number += 1
        self.level.ppvs_bought += 1
        self.consecutive_rejections = 0  # Purchase resets rejection counter

    # ─── Cooldown ───────────────────────────────────────

    def enter_cooldown(self):
        """Enter reduced-intimacy mode (less sales pressure, lighter tone)."""
        self.cooldown = True

    def exit_cooldown(self):
        """Exit reduced-intimacy mode."""
        self.cooldown = False

    def is_cooldown_rapport(self) -> bool:
        """True if currently in cooldown AND in RAPPORT phase."""
        return self.cooldown and self._phase == SpiralPhase.RAPPORT

    def record_rejection(self):
        """Track a fan rejecting/skipping a PPV offer."""
        self.consecutive_rejections += 1
        if self.consecutive_rejections >= 2:
            self.enter_cooldown()

    # ─── Ghost / Warmup ─────────────────────────────────

    def enter_warmup(self):
        """Enter warmup mode after ghosting — faster re-rapport."""
        self._warmup = True

    def exit_warmup(self):
        self._warmup = False

    @property
    def is_warmup(self) -> bool:
        return self._warmup

    # ─── Aftercare ──────────────────────────────────────

    def complete_aftercare(self):
        """Complete aftercare — transition back to RAPPORT at current level."""
        if self._phase != SpiralPhase.AFTERCARE:
            raise ValueError("Cannot complete aftercare: not in AFTERCARE phase")
        self.transition(SpiralPhase.RAPPORT)