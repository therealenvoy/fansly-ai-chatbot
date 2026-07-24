"""Churn Predictor.

Calculates fan churn risk based on recency of purchases, messages,
and sentiment, then routes to appropriate intervention strategies.
"""

from datetime import datetime, timedelta


class ChurnPredictor:
    """Predicts fan churn risk and recommends intervention.

    Uses a weighted formula combining purchase recency (50%), message
    recency (30%), and sentiment (20%) to produce a 0.0-1.0 risk score.

    Attributes:
        _last_reengagement: Per-fan mapping of when they were last
            re-engaged, used to avoid over-messaging.
    """

    def __init__(self) -> None:
        self._last_reengagement: dict[str, datetime] = {}

    # ── calculate_risk ─────────────────────────────────────────────────

    def calculate_risk(
        self,
        days_since_last_purchase: int,
        days_since_last_message: int,
        sentiment_score: float,
    ) -> float:
        """Calculate churn risk score from fan activity signals.

        Formula:
            (days_since_purchase/90 * 0.5) +
            (days_since_message/30  * 0.3) +
            ((1 - sentiment_score)/2 * 0.2)

        The result is clamped to [0.0, 1.0].

        Args:
            days_since_last_purchase: Days since the fan's last purchase.
            days_since_last_message: Days since the fan's last message.
            sentiment_score: Sentiment score in [-1.0, 1.0] where
                1.0 is maximally positive.

        Returns:
            Churn risk score between 0.0 and 1.0.
        """
        purchase_component = (days_since_last_purchase / 90.0) * 0.5
        message_component = (days_since_last_message / 30.0) * 0.3
        sentiment_component = ((1.0 - sentiment_score) / 2.0) * 0.2

        raw_risk = purchase_component + message_component + sentiment_component
        return max(0.0, min(1.0, raw_risk))

    # ── is_at_risk ─────────────────────────────────────────────────────

    def is_at_risk(self, risk_score: float) -> bool:
        """Determine whether a risk score indicates churn danger.

        Args:
            risk_score: Churn risk score from calculate_risk.

        Returns:
            True if risk_score > 0.6.
        """
        return risk_score > 0.6

    # ── get_intervention ───────────────────────────────────────────────

    def get_intervention(self, risk_score: float) -> str:
        """Map a risk score to the appropriate intervention tier.

        Args:
            risk_score: Churn risk score from calculate_risk.

        Returns:
            One of "none", "reengage_soft", "reengage_hard", or "win_back".
        """
        if risk_score < 0.3:
            return "none"
        elif risk_score < 0.6:
            return "reengage_soft"
        elif risk_score < 0.8:
            return "reengage_hard"
        else:
            return "win_back"

    # ── should_trigger_reengagement ────────────────────────────────────

    def should_trigger_reengagement(
        self, fan_id: str, current_risk: float
    ) -> bool:
        """Determine if re-engagement should be triggered for a fan.

        Returns True only if the fan is at risk and has not been
        re-engaged within the last 7 days.

        Args:
            fan_id: The fan's unique identifier.
            current_risk: The fan's current churn risk score.

        Returns:
            True if re-engagement should fire.
        """
        if not self.is_at_risk(current_risk):
            return False

        last = self._last_reengagement.get(fan_id)
        if last is None:
            return True

        return datetime.now() - last > timedelta(days=7)

    # ── mark_reengaged ─────────────────────────────────────────────────

    def mark_reengaged(self, fan_id: str) -> None:
        """Record that a re-engagement action was taken for a fan.

        This resets the cooldown so should_trigger_reengagement returns
        False for the next 7 days.

        Args:
            fan_id: The fan's unique identifier.
        """
        self._last_reengagement[fan_id] = datetime.now()
