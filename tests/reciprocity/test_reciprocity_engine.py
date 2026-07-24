"""Tests for the Reciprocity Engine."""

import pytest

from src.reciprocity.engine import ReciprocityEngine


class TestReciprocityEngine:
    """Tests for the ReciprocityEngine class."""

    # ── 1. debt starts at zero ───────────────────────────────────────
    def test_debt_starts_zero(self):
        """A new fan should have zero debt."""
        engine = ReciprocityEngine()
        assert engine.get_debt_level("fan1") == 0.0

    # ── 2. recording a free send increases debt ──────────────────────
    def test_record_free_send_increases_debt(self):
        """record_free_send should increase the fan's debt level."""
        engine = ReciprocityEngine()
        engine.record_free_send("fan1", 5.0)
        assert engine.get_debt_level("fan1") == 5.0

    # ── 3. multiple free sends accumulate debt ───────────────────────
    def test_multiple_free_sends_accumulate(self):
        """Multiple free sends should accumulate over time."""
        engine = ReciprocityEngine()
        engine.record_free_send("fan1", 3.0)
        engine.record_free_send("fan1", 7.0)
        engine.record_free_send("fan1", 2.5)
        assert engine.get_debt_level("fan1") == 12.5

    # ── 4. premium not ready without debt ───────────────────────────
    def test_premium_not_ready_without_debt(self):
        """is_premium_ready should return False when debt is zero."""
        engine = ReciprocityEngine()
        assert engine.is_premium_ready("fan1") is False

    # ── 5. premium ready after free send ─────────────────────────────
    def test_premium_ready_after_free_send(self):
        """is_premium_ready should return True after a free send creates debt."""
        engine = ReciprocityEngine()
        engine.record_free_send("fan1", 10.0)
        assert engine.is_premium_ready("fan1") is True

    # ── 6. price markup falls within 1.5x–3x range ──────────────────
    def test_price_markup_range(self):
        """suggest_premium_price should return a price between 1.5x and 3x base."""
        engine = ReciprocityEngine()
        base_price = 20.0

        # With no debt, price should still be in range
        price_no_debt = engine.suggest_premium_price("fan1", base_price)
        assert base_price * 1.5 <= price_no_debt <= base_price * 3.0

        # With some debt
        engine.record_free_send("fan1", 10.0)
        price_with_debt = engine.suggest_premium_price("fan1", base_price)
        assert base_price * 1.5 <= price_with_debt <= base_price * 3.0

        # With large debt — should approach 3x
        engine.record_free_send("fan2", 100.0)
        price_large_debt = engine.suggest_premium_price("fan2", base_price)
        assert base_price * 1.5 <= price_large_debt <= base_price * 3.0

    # ── 7. mark_premium_pitched resets readiness ─────────────────────
    def test_mark_pitched_resets_premium_ready(self):
        """After mark_premium_pitched, is_premium_ready should be False
        until another free send occurs."""
        engine = ReciprocityEngine()
        engine.record_free_send("fan1", 5.0)
        assert engine.is_premium_ready("fan1") is True

        engine.mark_premium_pitched("fan1")
        assert engine.is_premium_ready("fan1") is False

        # Debt still exists
        assert engine.get_debt_level("fan1") == 5.0

        # A new free send should make it ready again
        engine.record_free_send("fan1", 3.0)
        assert engine.is_premium_ready("fan1") is True

    # ── 8. never_send_on_request class flag ──────────────────────────
    def test_never_send_on_request_flag(self):
        """The class-level NEVER_SEND_ON_REQUEST flag should be True."""
        assert ReciprocityEngine.NEVER_SEND_ON_REQUEST is True
