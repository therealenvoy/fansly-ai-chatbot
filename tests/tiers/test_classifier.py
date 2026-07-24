"""
Tests for three-tier auto-classification with pricing rules.
"""
import pytest
from src.tiers.classifier import TierClassifier


@pytest.fixture
def classifier():
    """Create a fresh TierClassifier instance."""
    return TierClassifier()


class TestClassify:
    """Tests for classify(total_spent) → tier string."""

    def test_classify_whale(self, classifier):
        """Spend > $500 → 'whale'."""
        assert classifier.classify(500.01) == "whale"
        assert classifier.classify(1000.00) == "whale"
        assert classifier.classify(5000.00) == "whale"

    def test_classify_average(self, classifier):
        """Spend $50–$500 → 'average'."""
        assert classifier.classify(50.00) == "average"
        assert classifier.classify(250.00) == "average"
        assert classifier.classify(500.00) == "average"

    def test_classify_time_waster(self, classifier):
        """Spend < $50 → 'time_waster'."""
        assert classifier.classify(0.00) == "time_waster"
        assert classifier.classify(25.00) == "time_waster"
        assert classifier.classify(49.99) == "time_waster"


class TestUpdateTier:
    """Tests for update_tier(fan_id, new_spend) → new tier."""

    def test_update_tier_changes(self, classifier):
        """update_tier recalculates and returns the new tier string."""
        # Start as time_waster
        assert classifier.update_tier("fan1", 10.00) == "time_waster"
        # Upgrade to average
        assert classifier.update_tier("fan1", 75.00) == "average"
        # Upgrade to whale
        assert classifier.update_tier("fan1", 600.00) == "whale"
        # Downgrade back to time_waster
        assert classifier.update_tier("fan1", 5.00) == "time_waster"


class TestGetAllWhales:
    """Tests for get_all_whales(tier_map) → list of whale fan_ids."""

    def test_get_all_whales(self, classifier):
        """Returns only fan_ids currently in the whale tier."""
        tier_map = {
            "fan_a": "whale",
            "fan_b": "average",
            "fan_c": "time_waster",
            "fan_d": "whale",
            "fan_e": "average",
        }
        whales = classifier.get_all_whales(tier_map)
        assert sorted(whales) == ["fan_a", "fan_d"]

    def test_get_all_whales_empty(self, classifier):
        """No whales → empty list."""
        tier_map = {
            "fan_a": "time_waster",
            "fan_b": "average",
        }
        assert classifier.get_all_whales(tier_map) == []

    def test_get_all_whales_empty_map(self, classifier):
        """Empty tier_map → empty list."""
        assert classifier.get_all_whales({}) == []


class TestDowngradeTriggers:
    """Tests for check_downgrade based on inactivity."""

    def test_whale_downgrades_after_60_days(self, classifier):
        """Whale with 60+ days since last purchase → average."""
        assert classifier.check_downgrade("whale", 60) == "average"
        assert classifier.check_downgrade("whale", 90) == "average"

    def test_whale_stays_at_59_days(self, classifier):
        """Whale with <60 days stays whale."""
        assert classifier.check_downgrade("whale", 59) == "whale"
        assert classifier.check_downgrade("whale", 0) == "whale"

    def test_average_downgrades_after_90_days(self, classifier):
        """Average with 90+ days since last purchase → time_waster."""
        assert classifier.check_downgrade("average", 90) == "time_waster"
        assert classifier.check_downgrade("average", 120) == "time_waster"

    def test_average_stays_at_89_days(self, classifier):
        """Average with <90 days stays average."""
        assert classifier.check_downgrade("average", 89) == "average"
        assert classifier.check_downgrade("average", 0) == "average"

    def test_time_waster_never_downgrades(self, classifier):
        """Time_waster stays time_waster regardless of inactivity."""
        assert classifier.check_downgrade("time_waster", 365) == "time_waster"
        assert classifier.check_downgrade("time_waster", 0) == "time_waster"


class TestTierBasedPricing:
    """Tests for tier_based_ppv_price(tier, base_price) → adjusted price."""

    def test_tier_based_pricing(self, classifier):
        """Whales pay 2x, average 1x, time_wasters 0.5x."""
        base = 10.00
        assert classifier.tier_based_ppv_price("whale", base) == 20.00
        assert classifier.tier_based_ppv_price("average", base) == 10.00
        assert classifier.tier_based_ppv_price("time_waster", base) == 5.00

    def test_tier_based_pricing_different_base(self, classifier):
        """Multipliers work with different base prices."""
        assert classifier.tier_based_ppv_price("whale", 7.50) == 15.00
        assert classifier.tier_based_ppv_price("average", 7.50) == 7.50
        assert classifier.tier_based_ppv_price("time_waster", 7.50) == 3.75

    def test_unknown_tier_defaults_to_1x(self, classifier):
        """Unknown tier string → default 1x multiplier."""
        assert classifier.tier_based_ppv_price("premium", 10.00) == 10.00
