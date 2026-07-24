"""Tests for A/B Testing Engine."""

import pytest
from src.analytics.ab_testing import ABTestingEngine


class TestAssignVariant:
    def test_assign_variant_deterministic(self):
        """Same fan_id + test_name yields same variant."""
        engine = ABTestingEngine()
        variants = ["A", "B", "C"]
        first = engine.assign_variant("fan_001", "pricing_test", variants)
        second = engine.assign_variant("fan_001", "pricing_test", variants)
        assert first == second
        assert first in variants

    def test_assign_variant_distributes(self):
        """Different fans get distributed across variants."""
        engine = ABTestingEngine()
        variants = ["A", "B", "C"]
        assignments = set()
        for i in range(100):
            var = engine.assign_variant(f"fan_{i:04d}", "pricing_test", variants)
            assignments.add(var)
        # With 100 fans and 3 variants, we should see all variants
        assert len(assignments) == 3

    def test_assign_variant_different_test_names(self):
        """Same fan, different test -> potentially different variant."""
        engine = ABTestingEngine()
        variants = ["A", "B", "C"]
        a = engine.assign_variant("fan_001", "test_1", variants)
        b = engine.assign_variant("fan_001", "test_2", variants)
        # They could be same or different, but both should be valid
        assert a in variants
        assert b in variants


class TestRecordAndResults:
    def test_record_and_get_results(self):
        """Record outcomes and verify aggregated results."""
        engine = ABTestingEngine()
        variants = ["A", "B"]
        engine.clear_test("conversion_test")

        # Assign fans and record conversions
        for i in range(50):
            fan = f"fan_{i:04d}"
            var = engine.assign_variant(fan, "conversion_test", variants)
            # A gets ~40% conversion, B gets ~20% conversion
            if var == "A":
                converted = i < 20  # 20 out of ~25 (roughly)
            else:
                converted = i < 5   # 5 out of ~25 (roughly)
            engine.record_outcome(fan, "conversion_test", var, converted)

        results = engine.get_results("conversion_test")
        assert "A" in results
        assert "B" in results
        assert results["A"]["count"] > 0
        assert results["B"]["count"] > 0
        assert results["A"]["count"] + results["B"]["count"] == 50
        assert results["A"]["conversions"] + results["B"]["conversions"] > 0
        assert 0 <= results["A"]["rate"] <= 1.0
        assert 0 <= results["B"]["rate"] <= 1.0


class TestSignificance:
    def test_is_significant_true(self):
        """Winner has 20%+ relative improvement over loser."""
        engine = ABTestingEngine()
        variants = ["control", "treatment"]
        engine.clear_test("sig_test")

        # control: 10 of 100 = 10%
        # treatment: 15 of 100 = 15% -> 50% relative improvement
        for i in range(100):
            engine.record_outcome(
                f"c_{i}", "sig_test", "control", i < 10
            )
            engine.record_outcome(
                f"t_{i}", "sig_test", "treatment", i < 15
            )

        assert engine.is_significant("sig_test") is True

    def test_is_significant_false(self):
        """Small difference should not be significant."""
        engine = ABTestingEngine()
        variants = ["control", "treatment"]
        engine.clear_test("nosig_test")

        # control: 10 of 100 = 10%
        # treatment: 11 of 100 = 11% -> 10% relative improvement (< 20%)
        for i in range(100):
            engine.record_outcome(
                f"c_{i}", "nosig_test", "control", i < 10
            )
            engine.record_outcome(
                f"t_{i}", "nosig_test", "treatment", i < 11
            )

        assert engine.is_significant("nosig_test") is False

    def test_is_significant_no_data(self):
        """No data returns False."""
        engine = ABTestingEngine()
        assert engine.is_significant("empty_test") is False


class TestPromoteWinner:
    def test_promote_winner(self):
        """Returns the winning variant name."""
        engine = ABTestingEngine()
        variants = ["A", "B", "C"]
        engine.clear_test("winner_test")

        for i in range(100):
            engine.record_outcome(
                f"a_{i}", "winner_test", "A", i < 30  # 30%
            )
            engine.record_outcome(
                f"b_{i}", "winner_test", "B", i < 10  # 10%
            )
            engine.record_outcome(
                f"c_{i}", "winner_test", "C", i < 50  # 50%
            )

        winner = engine.promote_winner("winner_test")
        assert winner == "C"


class TestClearTest:
    def test_clear_test_removes_data(self):
        """clear_test should remove all data for a test."""
        engine = ABTestingEngine()
        engine.record_outcome("fan_001", "clear_me", "A", True)
        assert engine.get_results("clear_me") != {}
        engine.clear_test("clear_me")
        assert engine.get_results("clear_me") == {}
