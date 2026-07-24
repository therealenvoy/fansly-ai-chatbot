"""Tests for FunnelStateMachine — RED phase (tests written before implementation)."""

import pytest
from src.funnel.state_machine import FunnelStateMachine, FunnelStage


class TestFunnelStateMachine:
    """All state machine tests."""

    def test_new_session_starts_at_rapport(self):
        """A brand-new funnel should be at RAPPORT."""
        fsm = FunnelStateMachine()
        assert fsm.current_stage == FunnelStage.RAPPORT

    def test_cannot_skip_to_offer_from_rapport(self):
        """Direct RAPPORT → OFFER is not in ALLOWED_TRANSITIONS."""
        fsm = FunnelStateMachine()
        with pytest.raises(ValueError):
            fsm.transition(FunnelStage.OFFER)

    def test_valid_progression_rapport_to_tease(self):
        """RAPPORT → TEASE is a valid single-step transition."""
        fsm = FunnelStateMachine()
        fsm.transition(FunnelStage.TEASE)
        assert fsm.current_stage == FunnelStage.TEASE

    def test_full_funnel_progression(self):
        """Walk through all 5 stages in order."""
        fsm = FunnelStateMachine()
        fsm.transition(FunnelStage.TEASE)
        fsm.transition(FunnelStage.OFFER)
        fsm.transition(FunnelStage.HANDLE)
        fsm.transition(FunnelStage.CLOSE)
        assert fsm.current_stage == FunnelStage.CLOSE

    def test_cannot_move_backward(self):
        """Direct backward jumps (e.g. OFFER → RAPPORT) should raise ValueError."""
        fsm = FunnelStateMachine()
        fsm.transition(FunnelStage.TEASE)
        fsm.transition(FunnelStage.OFFER)
        with pytest.raises(ValueError):
            fsm.transition(FunnelStage.RAPPORT)

    def test_ppv_blocked_in_rapport(self):
        """PPV should NOT be allowed at RAPPORT."""
        fsm = FunnelStateMachine()
        assert fsm.can_send_ppv() is False

    def test_ppv_allowed_in_offer(self):
        """PPV should be allowed from OFFER onward."""
        fsm = FunnelStateMachine()
        fsm.transition(FunnelStage.TEASE)
        fsm.transition(FunnelStage.OFFER)
        assert fsm.can_send_ppv() is True

    def test_min_messages_before_tease(self):
        """min_messages_before_tease should return remaining messages needed."""
        fsm = FunnelStateMachine()
        # No rapport messages yet → need 2
        assert fsm.min_messages_before_tease() == 2