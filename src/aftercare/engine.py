"""Aftercare Engine.

Triggers tiered aftercare plans based on purchase amount.
Small (<$20): thank_you only.
Medium ($20-$100): selfie + thanks.
Large ($100+): voice + selfie + followup (24 h).

Initial aftercare is delayed by 5 minutes. Followup is due 24 hours
after the plan was created.
"""

import time
from dataclasses import dataclass, field


@dataclass
class AftercarePlan:
    """Aftercare plan generated from a purchase.

    Attributes:
        fan_id: The fan identifier.
        purchase_amount: The purchase amount in dollars.
        actions: Ordered list of aftercare actions to perform.
        delay_minutes: Delay before the initial aftercare is due (default 5).
        followup_hours: Hours until follow-up is due, or None.
        created_at: Unix timestamp when the plan was created.
        initial_sent: Whether the initial aftercare has been sent.
        followup_sent: Whether the follow-up has been sent.
    """

    fan_id: str
    purchase_amount: float
    actions: list[str]
    delay_minutes: int = 5
    followup_hours: int | None = None
    created_at: float = field(default_factory=time.time)
    initial_sent: bool = False
    followup_sent: bool = False


class AftercareEngine:
    """Engine that manages aftercare plans triggered by purchases.

    Plans are stored in memory keyed by fan_id. Each plan tracks
    whether the initial aftercare and optional followup have been sent.

    Attributes:
        plans: Internal storage of AftercarePlans keyed by fan_id.
    """

    def __init__(self) -> None:
        self.plans: dict[str, AftercarePlan] = {}

    # ── trigger_aftercare ───────────────────────────────────────────

    def trigger_aftercare(
        self, purchase_amount: float, fan_id: str
    ) -> AftercarePlan:
        """Generate a tiered aftercare plan based on the purchase amount.

        * < $20   → thank_you
        * $20–100 → selfie + thanks
        * $100+   → voice + selfie + followup (24 h)

        Args:
            purchase_amount: Dollar amount of the purchase.
            fan_id: The fan's unique identifier.

        Returns:
            An AftercarePlan with tiered actions.
        """
        if purchase_amount < 20:
            actions = ["thank_you"]
            followup_hours = None
        elif purchase_amount < 100:
            actions = ["selfie", "thanks"]
            followup_hours = None
        else:
            actions = ["voice", "selfie", "followup"]
            followup_hours = 24

        plan = AftercarePlan(
            fan_id=fan_id,
            purchase_amount=purchase_amount,
            actions=actions,
            followup_hours=followup_hours,
        )
        self.plans[fan_id] = plan
        return plan

    # ── is_aftercare_due ────────────────────────────────────────────

    def is_aftercare_due(self, fan_id: str) -> bool:
        """Check whether any aftercare is due for a fan.

        Returns True when:
        * Initial aftercare has not been sent AND the delay has elapsed.
        * Followup has not been sent AND the followup window has elapsed.

        Args:
            fan_id: The fan's unique identifier.

        Returns:
            True if aftercare is due, False otherwise.
        """
        plan = self.plans.get(fan_id)
        if plan is None:
            return False

        now = time.time()
        elapsed = now - plan.created_at

        # Initial aftercare due?
        if not plan.initial_sent and elapsed >= plan.delay_minutes * 60:
            return True

        # Followup due?
        if (
            plan.followup_hours is not None
            and not plan.followup_sent
            and elapsed >= plan.followup_hours * 3600
        ):
            return True

        return False

    # ── mark_aftercare_sent ─────────────────────────────────────────

    def mark_aftercare_sent(self, fan_id: str) -> None:
        """Mark aftercare as sent for the given fan.

        The first call marks the initial aftercare. The second call
        marks the followup (if one exists). Subsequent calls are no-ops.

        Args:
            fan_id: The fan's unique identifier.

        Raises:
            ValueError: If no plan exists for this fan.
        """
        plan = self.plans.get(fan_id)
        if plan is None:
            raise ValueError(f"No aftercare plan for fan '{fan_id}'")

        if not plan.initial_sent:
            plan.initial_sent = True
        elif not plan.followup_sent:
            plan.followup_sent = True