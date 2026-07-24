"""Reciprocity Engine.

Tracks free content sent to fans and determines when a premium pitch
is appropriate, with dynamic pricing based on accumulated debt.
"""


class ReciprocityEngine:
    """Engine that tracks free-content debt and manages premium readiness.

    Every free send (photo, voice, custom content) builds a "debt"
    that the fan should reciprocate.  Once debt > 0 the fan is
    eligible for a premium pitch.  After pitching, the flag is cleared
    until the next free send.

    Attributes:
        NEVER_SEND_ON_REQUEST: Class-level flag — always True (this
            engine never sends content on fan request; the creator
            initiates all sends).
        _debts: Per-fan accumulated value of free content.
        _pitched: Set of fans who have been pitched since their last
            free send.
    """

    NEVER_SEND_ON_REQUEST: bool = True

    def __init__(self) -> None:
        self._debts: dict[str, float] = {}
        self._pitched: set[str] = set()

    # ── record_free_send ─────────────────────────────────────────────

    def record_free_send(self, fan_id: str, content_value: float) -> None:
        """Log free content sent to a fan.

        Increments the fan's debt and resets the premium-pitched flag
        (new free content makes them eligible for another pitch).

        Args:
            fan_id: The fan's unique identifier.
            content_value: Estimated value of the free content in dollars.
        """
        self._debts[fan_id] = self._debts.get(fan_id, 0.0) + content_value
        self._pitched.discard(fan_id)

    # ── get_debt_level ───────────────────────────────────────────────

    def get_debt_level(self, fan_id: str) -> float:
        """Return the total value of free content sent to a fan.

        Args:
            fan_id: The fan's unique identifier.

        Returns:
            Accumulated debt in dollars (0.0 for unknown fans).
        """
        return self._debts.get(fan_id, 0.0)

    # ── is_premium_ready ─────────────────────────────────────────────

    def is_premium_ready(self, fan_id: str) -> bool:
        """Check whether a premium pitch is appropriate.

        Returns True when the fan has accumulated debt (> 0) and has
        not been pitched since their last free send.

        Args:
            fan_id: The fan's unique identifier.

        Returns:
            True if the fan is ready for a premium pitch.
        """
        return self.get_debt_level(fan_id) > 0.0 and fan_id not in self._pitched

    # ── suggest_premium_price ────────────────────────────────────────

    def suggest_premium_price(self, fan_id: str, base_price: float) -> float:
        """Suggest a premium price with a markup based on accumulated debt.

        The multiplier scales linearly from 1.5× (no debt) to 3.0×
        ($15+ debt), clamped to [1.5, 3.0].

        Args:
            fan_id: The fan's unique identifier.
            base_price: The base price for the premium content.

        Returns:
            Suggested price with debt-based markup applied.
        """
        debt = self.get_debt_level(fan_id)
        multiplier = min(3.0, 1.5 + debt * 0.1)
        return round(base_price * multiplier, 2)

    # ── mark_premium_pitched ─────────────────────────────────────────

    def mark_premium_pitched(self, fan_id: str) -> None:
        """Mark that a premium pitch has been made to the fan.

        After this call, is_premium_ready will return False until the
        next free send resets the flag.

        Args:
            fan_id: The fan's unique identifier.
        """
        self._pitched.add(fan_id)
