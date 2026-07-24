"""
Three-tier auto-classification for fan spending levels.

Tiers:
    - time_waster: total spent < $50
    - average:     total spent $50–$500
    - whale:       total spent > $500

Includes inactivity-based downgrade triggers and tier-based PPV pricing.
"""


class TierClassifier:
    """Classifies fans into spending tiers and applies tier-based rules."""

    # Spending thresholds
    THRESHOLD_TIME_WASTER = 50.0
    THRESHOLD_WHALE = 500.0

    # Inactivity downgrade thresholds (days)
    WHALE_DOWNGRADE_DAYS = 60
    AVERAGE_DOWNGRADE_DAYS = 90

    # PPV price multipliers per tier
    PRICE_MULTIPLIERS: dict[str, float] = {
        "whale": 2.0,
        "average": 1.0,
        "time_waster": 0.5,
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, total_spent: float) -> str:
        """Classify a fan based on their total spend.

        Args:
            total_spent: Cumulative amount the fan has spent in dollars.

        Returns:
            One of "time_waster", "average", or "whale".
        """
        if total_spent < self.THRESHOLD_TIME_WASTER:
            return "time_waster"
        if total_spent <= self.THRESHOLD_WHALE:
            return "average"
        return "whale"

    def update_tier(self, fan_id: str, new_spend: float) -> str:
        """Recalculate and return the fan's new tier based on updated spend.

        Args:
            fan_id: Unique identifier for the fan.
            new_spend: The fan's updated total spend in dollars.

        Returns:
            The new tier string ("time_waster", "average", or "whale").
        """
        return self.classify(new_spend)

    def get_all_whales(self, tier_map: dict) -> list[str]:
        """Return all fan_ids currently in the whale tier.

        Args:
            tier_map: Mapping of fan_id → tier string.

        Returns:
            List of fan_ids whose tier is "whale".
        """
        return [fan_id for fan_id, tier in tier_map.items() if tier == "whale"]

    def check_downgrade(self, current_tier: str, days_since_last_purchase: int) -> str:
        """Check whether a fan should be downgraded due to inactivity.

        Downgrade rules:
            - whale   with >= 60 days since last purchase → average
            - average with >= 90 days since last purchase → time_waster
            - time_waster never downgrades

        Args:
            current_tier: The fan's current tier string.
            days_since_last_purchase: Days elapsed since last purchase.

        Returns:
            The (possibly downgraded) tier string.
        """
        if current_tier == "whale" and days_since_last_purchase >= self.WHALE_DOWNGRADE_DAYS:
            return "average"
        if current_tier == "average" and days_since_last_purchase >= self.AVERAGE_DOWNGRADE_DAYS:
            return "time_waster"
        return current_tier

    def tier_based_ppv_price(self, tier: str, base_price: float) -> float:
        """Calculate the PPV price for a fan based on their tier.

        Multipliers:
            - whale:        2.0x
            - average:      1.0x
            - time_waster:  0.5x
            - unknown tier: 1.0x (safe default)

        Args:
            tier: The fan's tier string.
            base_price: The base price in dollars.

        Returns:
            Adjusted price as a float.
        """
        multiplier = self.PRICE_MULTIPLIERS.get(tier, 1.0)
        return base_price * multiplier
