"""Tests for the Aftercare Engine."""

import time

import pytest

from src.aftercare.engine import AftercareEngine, AftercarePlan


class TestAftercarePlan:
    """Tests for the AftercarePlan dataclass."""

    def test_plan_creation_defaults(self):
        """Plan should have correct defaults and store all fields."""
        plan = AftercarePlan(
            fan_id="fan1",
            purchase_amount=10.0,
            actions=["thank_you"],
        )
        assert plan.fan_id == "fan1"
        assert plan.purchase_amount == 10.0
        assert plan.actions == ["thank_you"]
        assert plan.delay_minutes == 5
        assert plan.followup_hours is None
        assert plan.initial_sent is False
        assert plan.followup_sent is False
        assert isinstance(plan.created_at, float)


class TestAftercareEngine:
    """Tests for the AftercareEngine class."""

    # ── 1. small purchase gets thanks only ──────────────────────────
    def test_small_purchase_gets_thanks_only(self):
        """Purchases under $20 should only trigger a thank_you action."""
        engine = AftercareEngine()
        plan = engine.trigger_aftercare(purchase_amount=10.0, fan_id="fan1")
        assert plan.actions == ["thank_you"]
        assert plan.followup_hours is None

    # ── 2. medium purchase gets selfie + thanks ─────────────────────
    def test_medium_purchase_gets_selfie_and_thanks(self):
        """Purchases $20–$100 should trigger selfie + thanks actions."""
        engine = AftercareEngine()
        plan = engine.trigger_aftercare(purchase_amount=50.0, fan_id="fan2")
        assert plan.actions == ["selfie", "thanks"]
        assert plan.followup_hours is None

    # ── 3. large purchase gets full aftercare ───────────────────────
    def test_large_purchase_gets_full_aftercare(self):
        """Purchases $100+ should trigger voice + selfie + followup."""
        engine = AftercareEngine()
        plan = engine.trigger_aftercare(purchase_amount=150.0, fan_id="fan3")
        assert plan.actions == ["voice", "selfie", "followup"]
        assert plan.followup_hours == 24

    # ── 4. aftercare is not due immediately, due after 5 min ────────
    def test_aftercare_delay_is_5_minutes(self):
        """Aftercare should NOT be due immediately, but due after 5 minutes."""
        engine = AftercareEngine()
        plan = engine.trigger_aftercare(purchase_amount=50.0, fan_id="fan4")

        # Not due immediately after creation
        assert engine.is_aftercare_due("fan4") is False

        # Simulate 5 min + 1 sec passing
        plan.created_at = time.time() - (5 * 60 + 1)
        assert engine.is_aftercare_due("fan4") is True

    # ── 5. large purchase followup is due after 24 h ────────────────
    def test_followup_delay_is_24_hours(self):
        """Large purchase followup should NOT be due until 24 hours have passed."""
        engine = AftercareEngine()
        plan = engine.trigger_aftercare(purchase_amount=150.0, fan_id="fan5")

        # Plan metadata
        assert plan.followup_hours == 24

        # Not due immediately
        assert engine.is_aftercare_due("fan5") is False

        # After 5 minutes, initial aftercare is due
        plan.created_at = time.time() - (5 * 60 + 1)
        assert engine.is_aftercare_due("fan5") is True

        # Send initial — followup should NOT be due yet (only 5 min elapsed)
        engine.mark_aftercare_sent("fan5")
        assert engine.is_aftercare_due("fan5") is False

        # After 24 hours, followup is due
        plan.created_at = time.time() - (24 * 3600 + 1)
        assert engine.is_aftercare_due("fan5") is True

    # ── 6. not due for unknown fan ──────────────────────────────────
    def test_not_due_for_new_fan(self):
        """is_aftercare_due should return False for a fan with no plan."""
        engine = AftercareEngine()
        assert engine.is_aftercare_due("unknown_fan") is False

    # ── 7. mark_sent tracks initial then followup ───────────────────
    def test_mark_sent_tracks_state(self):
        """mark_aftercare_sent should flip initial_sent then followup_sent."""
        engine = AftercareEngine()
        plan = engine.trigger_aftercare(purchase_amount=150.0, fan_id="fan6")

        # Backdate so initial is due
        plan.created_at = time.time() - (5 * 60 + 1)
        assert engine.is_aftercare_due("fan6") is True

        # Mark initial sent
        engine.mark_aftercare_sent("fan6")
        assert plan.initial_sent is True
        assert plan.followup_sent is False
        # No longer due (followup not due yet)
        assert engine.is_aftercare_due("fan6") is False

        # Backdate so followup is due
        plan.created_at = time.time() - (24 * 3600 + 1)
        assert engine.is_aftercare_due("fan6") is True

        # Mark followup sent
        engine.mark_aftercare_sent("fan6")
        assert plan.followup_sent is True
        # Nothing left to send
        assert engine.is_aftercare_due("fan6") is False

    def test_mark_sent_raises_for_unknown_fan(self):
        """mark_aftercare_sent should raise ValueError for unknown fan."""
        engine = AftercareEngine()
        with pytest.raises(ValueError):
            engine.mark_aftercare_sent("nobody")
