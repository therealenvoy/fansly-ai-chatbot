"""Delay Manager for staged conversation timing.

Configurable delays per funnel stage, with wait-message generation
and validation that checks whether actual delays fall within tolerance.
"""

from __future__ import annotations

DEFAULT_DELAYS: dict[str, int] = {
    "rapport": 0,
    "tease": 60,
    "offer": 90,
    "handle": 120,
    "close": 150,
}

# Maximum seconds tolerated for a zero-delay stage.
ZERO_DELAY_MAX: float = 1.0

# Tolerance ratio for non-zero delays (50%).
TOLERANCE: float = 0.5


class DelayManager:
    """Manages configurable stage delays for the sales funnel.

    Each stage has a target delay in seconds.  ``wait_message`` produces
    human-facing text, and ``validate_delay`` checks whether an actual
    delay is within 50 % of the target.

    Attributes:
        _delays: Mapping of stage name → target delay in seconds.
    """

    def __init__(self, delays: dict[str, int] | None = None) -> None:
        """Initialise with optional custom delay overrides.

        Args:
            delays: Partial or full override for default stage delays.
        """
        self._delays: dict[str, int] = {**DEFAULT_DELAYS, **(delays or {})}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_delay(self, stage: str) -> int:
        """Return the configured delay in seconds for *stage*.

        Args:
            stage: Funnel stage name (e.g. ``"tease"``).

        Returns:
            Delay in seconds.

        Raises:
            KeyError: If *stage* is not a recognised stage.
        """
        return self._delays[stage]

    def wait_message(self, stage: str) -> str:
        """Return a human-readable waiting prompt for *stage*.

        Rapports (0 s delay) return an immediate-reply message; all other
        stages return ``"give me X minutes..."``.

        Args:
            stage: Funnel stage name.

        Returns:
            Waiting text.
        """
        seconds = self.get_delay(stage)
        if seconds == 0:
            return "I'll reply right away!"

        minutes = seconds // 60
        return f"give me {minutes} minutes..."

    def validate_delay(self, actual_seconds: float, stage: str) -> bool:
        """Return ``True`` if *actual_seconds* is within tolerance of the
        target delay for *stage*.

        For non-zero targets the tolerance is ±50 %; for a zero-delay
        stage any value ≤ 1 second is accepted.

        Args:
            actual_seconds: Measured delay in seconds.
            stage: Funnel stage name.

        Returns:
            ``True`` if the delay is acceptable.
        """
        target = self.get_delay(stage)

        if target == 0:
            return actual_seconds <= ZERO_DELAY_MAX

        deviation = abs(actual_seconds - target) / target
        return deviation <= TOLERANCE
