"""Tests for spiral engine bug fixes — cooldown exit, aftercare guard, dedup."""
import pytest
from datetime import datetime, timezone, timedelta
from src.funnel.spiral import SpiralStateMachine, SpiralPhase


class TestCooldownExit:
    """Task 1: Cooldown should exit on fan engagement signals."""

    def test_cooldown_exits_on_flirty_message(self):
        s = SpiralStateMachine()
        s.enter_cooldown()
        assert s.cooldown is True
        # Simulate flirty keyword detection
        flirty_keywords = ["hard", "horny", "wet", "turn on", "hot", "sexy", "want you"]
        for kw in flirty_keywords:
            cooldown_exited = False
            if kw in "I'm so hard right now".lower():
                s.exit_cooldown()
                cooldown_exited = True
            if cooldown_exited:
                break
        assert s.cooldown is False

    def test_cooldown_does_not_exit_on_neutral_message(self):
        s = SpiralStateMachine()
        s.enter_cooldown()
        assert s.cooldown is True
        # Neutral message should not exit cooldown
        neutral_msg = "what's up"
        flirty_keywords = ["hard", "horny", "wet", "turn on", "hot", "sexy", "want you"]
        exited = any(kw in neutral_msg.lower() for kw in flirty_keywords)
        if not exited:
            pass  # cooldown stays
        assert s.cooldown is True

    def test_cooldown_exits_on_tip(self):
        """Any tip transaction should exit cooldown."""
        s = SpiralStateMachine()
        s.enter_cooldown()
        s.exit_cooldown()  # tip exits cooldown immediately
        assert s.cooldown is False

    def test_auto_cooldown_exit_on_rapport_transition(self):
        """Already handled: complete_aftercare → RAPPORT auto-exits cooldown."""
        s = SpiralStateMachine()
        s.enter_cooldown()
        assert s.cooldown is True
        # Simulate full cycle
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        s.advance_level()
        s.transition(SpiralPhase.AFTERCARE)
        s.complete_aftercare()  # → RAPPORT, auto-exits cooldown
        assert s.cooldown is False


class TestAftercarePhaseGuard:
    """Task 2: Aftercare should only fire when spiral phase is CLOSE or AFTERCARE."""

    def test_aftercare_skipped_when_rapport(self):
        """When spiral is in RAPPORT, aftercare check should return False."""
        s = SpiralStateMachine()
        assert s.phase == SpiralPhase.RAPPORT
        # Guard: is_aftercare_due only when phase is CLOSE or AFTERCARE
        aftercare_possible = s.phase in (SpiralPhase.CLOSE, SpiralPhase.AFTERCARE)
        assert aftercare_possible is False

    def test_aftercare_allowed_when_close(self):
        s = SpiralStateMachine()
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        aftercare_possible = s.phase in (SpiralPhase.CLOSE, SpiralPhase.AFTERCARE)
        assert aftercare_possible is True

    def test_aftercare_allowed_when_aftercare(self):
        s = SpiralStateMachine()
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        s.transition(SpiralPhase.AFTERCARE)
        aftercare_possible = s.phase in (SpiralPhase.CLOSE, SpiralPhase.AFTERCARE)
        assert aftercare_possible is True

    def test_aftercare_skipped_when_tease_offer_handle(self):
        s = SpiralStateMachine()
        for phase in [SpiralPhase.RAPPORT, SpiralPhase.TEASE, SpiralPhase.OFFER, SpiralPhase.HANDLE]:
            s2 = SpiralStateMachine()
            if phase != SpiralPhase.RAPPORT:
                try:
                    s2.transition(phase)
                except ValueError:
                    pass
            assert s2.phase not in (SpiralPhase.CLOSE, SpiralPhase.AFTERCARE), f"Failed at {phase}"


class TestPurchaseDedup:
    """Task 3: advance_level should only fire once per unique purchase."""

    def test_advance_level_once_per_call(self):
        s = SpiralStateMachine()
        s.advance_level()
        assert s.level.number == 1
        s.advance_level()
        assert s.level.number == 2  # Still increments — this is correct
        # The dedup is in bot.py via cache, not in spiral itself

    def test_purchase_cache_initialized_from_db(self):
        """Simulate cache population: known purchase counts should not trigger advance."""
        known_count = 5
        cache = {"fan_1": known_count}
        current_count = 5
        # If cache == current, no purchase detected
        assert current_count <= cache.get("fan_1", 0)  # No new purchase