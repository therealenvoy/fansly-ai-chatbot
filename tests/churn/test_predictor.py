"""Tests for the Churn Predictor."""

from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

import pytest

from src.churn.predictor import ChurnPredictor


class TestChurnPredictor:
    """Tests for the ChurnPredictor class."""

    # ── 1. risk zero for active fan ───────────────────────────────────
    def test_risk_zero_for_active_fan(self):
        """An extremely active fan should have near-zero churn risk."""
        predictor = ChurnPredictor()
        risk = predictor.calculate_risk(
            days_since_last_purchase=0,
            days_since_last_message=0,
            sentiment_score=1.0,
        )
        assert risk == pytest.approx(0.0, abs=0.01)

    # ── 2. risk high for lapsed fan ───────────────────────────────────
    def test_risk_high_for_lapsed(self):
        """A fully lapsed fan (90+ days, 0 sentiment) should have high risk."""
        predictor = ChurnPredictor()
        risk = predictor.calculate_risk(
            days_since_last_purchase=90,
            days_since_last_message=30,
            sentiment_score=0.0,
        )
        # (90/90 * 0.5) + (30/30 * 0.3) + ((1-0)/2 * 0.2)
        # = 0.5 + 0.3 + 0.1 = 0.9
        assert risk == pytest.approx(0.9, abs=0.01)

    # ── 3. at_risk threshold ──────────────────────────────────────────
    def test_at_risk_threshold(self):
        """Risk > 0.6 should return True for is_at_risk."""
        predictor = ChurnPredictor()
        assert predictor.is_at_risk(0.61) is True
        assert predictor.is_at_risk(0.6) is False
        assert predictor.is_at_risk(0.0) is False

    # ── 4. intervention levels ────────────────────────────────────────
    def test_intervention_levels(self):
        """get_intervention should return correct level for each risk band."""
        predictor = ChurnPredictor()
        assert predictor.get_intervention(0.0) == "none"
        assert predictor.get_intervention(0.29) == "none"
        assert predictor.get_intervention(0.3) == "reengage_soft"
        assert predictor.get_intervention(0.59) == "reengage_soft"
        assert predictor.get_intervention(0.6) == "reengage_hard"
        assert predictor.get_intervention(0.79) == "reengage_hard"
        assert predictor.get_intervention(0.8) == "win_back"
        assert predictor.get_intervention(1.0) == "win_back"

    # ── 5. reengagement trigger ───────────────────────────────────────
    def test_reengagement_trigger(self):
        """should_trigger_reengagement should only trigger when at risk
        and not re-engaged in the last 7 days."""
        predictor = ChurnPredictor()

        # Fan at risk, never re-engaged → should trigger
        assert predictor.should_trigger_reengagement("fan1", 0.7) is True

        # Fan at risk, mark re-engaged → should NOT trigger
        predictor.mark_reengaged("fan1")
        assert predictor.should_trigger_reengagement("fan1", 0.7) is False

        # Fan not at risk (even if never re-engaged) → should NOT trigger
        assert predictor.should_trigger_reengagement("fan2", 0.5) is False

        # Fan at risk, re-engaged more than 7 days ago → should trigger
        predictor = ChurnPredictor()
        old_date = datetime.now() - timedelta(days=8)
        predictor._last_reengagement["fan3"] = old_date
        assert predictor.should_trigger_reengagement("fan3", 0.7) is True

    # ── 6. risk clamping to 1 ─────────────────────────────────────────
    def test_risk_clamping_to_1(self):
        """Risk score should be clamped to a maximum of 1.0."""
        predictor = ChurnPredictor()
        risk = predictor.calculate_risk(
            days_since_last_purchase=365,
            days_since_last_message=365,
            sentiment_score=-1.0,
        )
        # Formula gives > 1, but must be clamped to 1.0
        assert risk == pytest.approx(1.0, abs=0.01)
