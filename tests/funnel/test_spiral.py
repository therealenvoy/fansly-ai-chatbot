"""Tests for SpiralStateMachine — the perpetual escalation engine."""
import pytest
from src.funnel.spiral import SpiralStateMachine, SpiralPhase, EscalationLevel


class TestSpiralStateMachine:
    """Core state machine tests."""

    def test_new_session_starts_at_rapport_level_0(self):
        s = SpiralStateMachine()
        assert s.phase == SpiralPhase.RAPPORT
        assert s.level == EscalationLevel()
        assert s.level.number == 0
        assert s.cooldown is False

    def test_valid_rapport_to_tease(self):
        s = SpiralStateMachine()
        s.transition(SpiralPhase.TEASE)
        assert s.phase == SpiralPhase.TEASE

    def test_cannot_skip_to_offer_from_rapport(self):
        s = SpiralStateMachine()
        with pytest.raises(ValueError):
            s.transition(SpiralPhase.OFFER)

    def test_cannot_skip_to_close_from_rapport(self):
        s = SpiralStateMachine()
        with pytest.raises(ValueError):
            s.transition(SpiralPhase.CLOSE)

    def test_full_cycle_progression(self):
        """Walk through entire cycle at level 0."""
        s = SpiralStateMachine()
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        s.transition(SpiralPhase.AFTERCARE)
        assert s.phase == SpiralPhase.AFTERCARE
        # Aftercare → back to RAPPORT at next level
        s.transition(SpiralPhase.RAPPORT)
        assert s.phase == SpiralPhase.RAPPORT

    def test_level_advances_on_purchase(self):
        """Marking a purchase should advance the level by 1."""
        s = SpiralStateMachine()
        # Go through first cycle
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        # Fan bought — advance level
        s.advance_level()
        assert s.level.number == 1
        assert s.level.ppvs_bought == 1

    def test_level_affects_ppv_allowed(self):
        """PPV should be allowed from OFFER stage."""
        s = SpiralStateMachine()
        assert s.can_send_ppv() is False  # RAPPORT
        s.transition(SpiralPhase.TEASE)
        assert s.can_send_ppv() is False  # TEASE
        s.transition(SpiralPhase.OFFER)
        assert s.can_send_ppv() is True   # OFFER
        s.transition(SpiralPhase.HANDLE)
        assert s.can_send_ppv() is True   # HANDLE
        s.transition(SpiralPhase.CLOSE)
        assert s.can_send_ppv() is True   # CLOSE
        s.transition(SpiralPhase.AFTERCARE)
        assert s.can_send_ppv() is False  # AFTERCARE (no selling)

    def test_cooldown_mode(self):
        s = SpiralStateMachine()
        s.enter_cooldown()
        assert s.cooldown is True
        s.exit_cooldown()
        assert s.cooldown is False

    def test_cooldown_rapport_is_less_intimate(self):
        """In cooldown, phase is RAPPORT but cooldown flag is set."""
        s = SpiralStateMachine()
        s.enter_cooldown()
        assert s.cooldown is True
        # Cooldown rapport should return a special flag
        assert s.is_cooldown_rapport() is True

    def test_cooldown_resets_on_engagement(self):
        """When fan re-engages in cooldown, bot can exit cooldown."""
        s = SpiralStateMachine()
        s.enter_cooldown()
        assert s.cooldown is True
        s.exit_cooldown()
        assert s.cooldown is False

    def test_aftercare_resets_to_rapport_next_level(self):
        """After aftercare finishes, go back to RAPPORT at next level."""
        s = SpiralStateMachine()
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        s.advance_level()  # Level now 1
        s.transition(SpiralPhase.AFTERCARE)
        s.complete_aftercare()
        assert s.phase == SpiralPhase.RAPPORT
        assert s.level.number == 1  # Level preserved
        assert s.level.ppvs_bought == 1

    def test_aftercare_counts_first_purchase(self):
        """Level should reflect total PPVs purchased."""
        s = SpiralStateMachine()
        assert s.level.ppvs_bought == 0
        s.advance_level()  # Bought 1
        s.advance_level()  # Bought 2
        s.advance_level()  # Bought 3
        assert s.level.number == 3
        assert s.level.ppvs_bought == 3

    def test_rejection_counters(self):
        """Track consecutive rejections for cooldown trigger."""
        s = SpiralStateMachine()
        assert s.consecutive_rejections == 0
        s.record_rejection()
        assert s.consecutive_rejections == 1
        s.record_rejection()
        assert s.consecutive_rejections == 2
        # After purchase, reset
        s.advance_level()
        assert s.consecutive_rejections == 0

    def test_auto_cooldown_after_2_rejections(self):
        """2 consecutive rejections should trigger cooldown."""
        s = SpiralStateMachine()
        s.record_rejection()
        assert s.cooldown is False
        s.record_rejection()
        assert s.cooldown is True

    def test_cannot_skip_aftercare(self):
        """Cannot go from CLOSE directly to RAPPORT — must go through AFTERCARE."""
        s = SpiralStateMachine()
        s.transition(SpiralPhase.TEASE)
        s.transition(SpiralPhase.OFFER)
        s.transition(SpiralPhase.HANDLE)
        s.transition(SpiralPhase.CLOSE)
        with pytest.raises(ValueError):
            s.transition(SpiralPhase.RAPPORT)

    def test_min_messages_before_tease(self):
        s = SpiralStateMachine()
        assert s.min_messages_before_tease() == 2
        s.record_rapport_message()
        assert s.min_messages_before_tease() == 1
        s.record_rapport_message()
        assert s.min_messages_before_tease() == 0

    def test_warmup_has_fewer_required_messages(self):
        """After ghosting, re-rapport should need fewer messages."""
        s = SpiralStateMachine()
        s.advance_level()  # Already bought 1
        s.enter_warmup()
        assert s.min_messages_before_tease() == 1  # Only 1 needed on warmup
        s.record_rapport_message()
        assert s.min_messages_before_tease() == 0