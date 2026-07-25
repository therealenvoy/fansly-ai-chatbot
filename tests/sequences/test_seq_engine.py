"""Tests for Sequence Engine — RED phase."""
import pytest
from datetime import datetime, timezone
from src.sequences.models import Sequence, SequenceStep, SequenceTrigger, StepStatus
from src.sequences.repository import SequenceRepository
from src.sequences.engine import SequenceEngine


@pytest.fixture
def repo():
    r = SequenceRepository(db_url="sqlite:///:memory:")
    r.create_tables()
    return r


@pytest.fixture
def engine(repo):
    return SequenceEngine(repo, creator_id="sunny")


@pytest.fixture
def seq_with_steps(repo):
    s = Sequence("Welcome Ladder", SequenceTrigger.NEW_SUB, "rapport")
    s = repo.save_sequence(s)
    s1 = repo.save_step(SequenceStep(sequence_id=s.id, position=1, media_id="m1", price=9.99, tease_script="Want to see the first one?", offer_script="Here it is 🔥"))
    s2 = repo.save_step(SequenceStep(sequence_id=s.id, position=2, media_id="m2", price=24.99, tease_script="Ready for more?", offer_script="This one's special 😈"))
    s.steps = [s1, s2]
    return s


class TestSequenceEngine:
    def test_next_ppv_no_sequences(self, engine):
        assert engine.get_next_ppv("fan_1", "rapport") is None

    def test_next_ppv_returns_step(self, engine, repo, seq_with_steps):
        result = engine.get_next_ppv("fan_1", "rapport")
        assert result is not None
        seq, step = result
        assert seq.name == "Welcome Ladder"
        assert step.position == 1
        assert step.price == 9.99
        assert step.tease_script == "Want to see the first one?"

    def test_next_ppv_after_first_sent(self, engine, repo, seq_with_steps):
        # Simulate step 1 sent
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[0])
        # Next PPV should be step 2
        result = engine.get_next_ppv("fan_1", "rapport")
        assert result is not None
        seq, step = result
        assert step.position == 2
        assert step.price == 24.99

    def test_next_ppv_after_purchase(self, engine, repo, seq_with_steps):
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[0])
        engine.mark_purchased("fan_1", seq_with_steps.id)
        # After purchase, should advance to step 2
        result = engine.get_next_ppv("fan_1", "rapport")
        assert result is not None
        seq, step = result
        assert step.position == 2

    def test_next_ppv_after_all_bought(self, engine, repo, seq_with_steps):
        # Mark all steps as sent + purchased
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[0])
        engine.mark_purchased("fan_1", seq_with_steps.id)
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[1])
        engine.mark_purchased("fan_1", seq_with_steps.id)
        # All steps done — no more PPV
        assert engine.get_next_ppv("fan_1", "rapport") is None

    def test_skipped_step_advances(self, engine, repo, seq_with_steps):
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[0])
        engine.mark_skipped("fan_1", seq_with_steps.id)
        # Should be on step 2 now
        result = engine.get_next_ppv("fan_1", "rapport")
        assert result is not None
        _, step = result
        assert step.position == 2

    def test_funnel_stage_matching(self, engine, repo):
        """Should prefer sequences matching the funnel stage."""
        s1 = repo.save_sequence(Sequence("Rapport Seq", SequenceTrigger.WELCOME, "rapport"))
        s2 = repo.save_sequence(Sequence("Tease Seq", SequenceTrigger.WELCOME, "tease"))
        repo.save_step(SequenceStep(sequence_id=s1.id, position=1, media_id="m1", price=5))
        repo.save_step(SequenceStep(sequence_id=s2.id, position=1, media_id="m2", price=10))
        s1.steps = repo.get_steps(s1.id)
        s2.steps = repo.get_steps(s2.id)

        result = engine.get_next_ppv("fan_1", "rapport")
        assert result is not None
        seq, step = result
        assert seq.name == "Rapport Seq"

    def test_whale_sequence_preferred_for_high_spenders(self, engine, repo):
        s_normal = repo.save_sequence(Sequence("Normal", SequenceTrigger.NEW_SUB, "rapport"))
        s_whale = repo.save_sequence(Sequence("VIP", SequenceTrigger.WHALE, "rapport"))
        repo.save_step(SequenceStep(sequence_id=s_normal.id, position=1, media_id="m1", price=5))
        repo.save_step(SequenceStep(sequence_id=s_whale.id, position=1, media_id="m2", price=99))

        result = engine.get_next_ppv("whale_fan", "rapport", fan_total_spent=500)
        assert result is not None
        seq, step = result
        assert seq.name == "VIP"

    def test_mark_sent_persists(self, engine, repo, seq_with_steps):
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[0])
        p = repo.get_progress("fan_1", seq_with_steps.id, "sunny")
        assert p is not None
        assert p.current_step == 2  # advanced to next step position
        assert p.status == StepStatus.SENT

    def test_mark_purchased_persists_bought_at(self, engine, repo, seq_with_steps):
        engine.mark_sent("fan_1", seq_with_steps, seq_with_steps.steps[0])
        engine.mark_purchased("fan_1", seq_with_steps.id)
        p = repo.get_progress("fan_1", seq_with_steps.id, "sunny")
        # After buying step 1 with step 2 available, status resets to PENDING for next step
        assert p.status == StepStatus.PENDING
        assert p.bought_at is not None

    def test_get_tease_script(self, engine, repo, seq_with_steps):
        tease = engine.get_active_tease_for_fan("fan_1", "rapport")
        assert tease == "Want to see the first one?"