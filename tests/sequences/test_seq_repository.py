"""Tests for PPV Sequence Repository — RED phase."""
import pytest
from datetime import datetime, timezone
from src.sequences.models import Sequence, SequenceStep, FanSequenceProgress, SequenceTrigger, StepStatus
from src.sequences.repository import SequenceRepository


@pytest.fixture
def repo():
    r = SequenceRepository(db_url="sqlite:///:memory:")
    r.create_tables()
    return r


class TestSequenceRepo:
    def test_save_and_get_sequence(self, repo):
        s = Sequence(name="Welcome Ladder", trigger=SequenceTrigger.NEW_SUB, funnel_stage="rapport")
        saved = repo.save_sequence(s)
        assert saved.id is not None

        fetched = repo.get_sequence(saved.id)
        assert fetched is not None
        assert fetched.name == "Welcome Ladder"
        assert fetched.trigger == SequenceTrigger.NEW_SUB

    def test_list_sequences(self, repo):
        repo.save_sequence(Sequence("S1", SequenceTrigger.WELCOME, "rapport"))
        repo.save_sequence(Sequence("S2", SequenceTrigger.WHALE, "tease"))
        all_seq = repo.list_sequences()
        assert len(all_seq) == 2

    def test_list_active_sequences(self, repo):
        repo.save_sequence(Sequence("Active", SequenceTrigger.WELCOME, "rapport"))
        s2 = Sequence("Inactive", SequenceTrigger.WHALE, "tease", is_active=False)
        repo.save_sequence(s2)
        active = repo.list_sequences(active_only=True)
        assert len(active) == 1
        assert active[0].name == "Active"

    def test_delete_sequence(self, repo):
        s = repo.save_sequence(Sequence("Del", SequenceTrigger.WELCOME, "rapport"))
        assert repo.get_sequence(s.id) is not None
        assert repo.delete_sequence(s.id) is True
        assert repo.get_sequence(s.id) is None
        assert repo.delete_sequence(s.id) is False

    def test_save_sequence_with_steps(self, repo):
        s = Sequence("Ladder", SequenceTrigger.NEW_SUB, "rapport")
        s.steps = [
            SequenceStep(sequence_id="", position=1, media_id="m1", price=9.99,
                         tease_script="Want to see?", offer_script="Here it is 🔥"),
            SequenceStep(sequence_id="", position=2, media_id="m2", price=24.99),
        ]
        saved = repo.save_sequence(s)
        steps = repo.get_steps(saved.id)
        assert len(steps) == 2
        assert steps[0].position == 1
        assert steps[0].tease_script == "Want to see?"
        assert steps[1].price == 24.99

    def test_atomic_sequence_replace_updates_ordered_steps(self, repo):
        sequence = Sequence(
            "Ladder",
            SequenceTrigger.WELCOME,
            "offer",
            steps=[
                SequenceStep(
                    sequence_id=0,
                    position=5,
                    media_id="fansly_media_1",
                    price=10,
                ),
                SequenceStep(
                    sequence_id=0,
                    position=2,
                    media_id="fansly_media_2",
                    price=20,
                ),
            ],
        )

        saved = repo.save_sequence_with_steps(sequence)

        assert saved.id is not None
        steps = repo.get_steps(saved.id)
        assert [step.position for step in steps] == [1, 2]
        assert [step.media_id for step in steps] == [
            "fansly_media_2",
            "fansly_media_1",
        ]

    def test_atomic_sequence_replace_rolls_back_on_invalid_step(
        self,
        repo,
    ):
        sequence = repo.save_sequence_with_steps(
            Sequence(
                "Original",
                SequenceTrigger.WELCOME,
                "offer",
                steps=[
                    SequenceStep(
                        sequence_id=0,
                        position=1,
                        media_id="fansly_media_1",
                        price=10,
                    )
                ],
            )
        )
        replacement = repo.get_sequence(sequence.id)
        replacement.name = "Broken update"
        replacement.steps = [
            SequenceStep(
                sequence_id=replacement.id,
                position=1,
                media_id=None,
                price=20,
            )
        ]

        with pytest.raises(Exception):
            repo.save_sequence_with_steps(replacement)

        persisted = repo.get_sequence(sequence.id)
        assert persisted.name == "Original"
        assert [step.media_id for step in persisted.steps] == [
            "fansly_media_1"
        ]

    def test_update_step(self, repo):
        s = repo.save_sequence(Sequence("Test", SequenceTrigger.WELCOME, "rapport"))
        step = SequenceStep(sequence_id=s.id, position=1, media_id="m1", price=9.99)
        saved_step = repo.save_step(step)
        saved_step.price = 14.99
        repo.save_step(saved_step)
        steps = repo.get_steps(s.id)
        assert steps[0].price == 14.99

    def test_reorder_steps(self, repo):
        s = repo.save_sequence(Sequence("Reorder", SequenceTrigger.WELCOME, "rapport"))
        s1 = repo.save_step(SequenceStep(sequence_id=s.id, position=1, media_id="a", price=5))
        s2 = repo.save_step(SequenceStep(sequence_id=s.id, position=2, media_id="b", price=10))
        repo.reorder_steps(s.id, [s2.id, s1.id])
        steps = repo.get_steps(s.id)
        assert steps[0].id == s2.id
        assert steps[0].position == 1
        assert steps[1].id == s1.id
        assert steps[1].position == 2

    def test_delete_step(self, repo):
        s = repo.save_sequence(Sequence("Test", SequenceTrigger.WELCOME, "rapport"))
        step = repo.save_step(SequenceStep(sequence_id=s.id, position=1, media_id="m1", price=5))
        steps = repo.get_steps(s.id)
        assert len(steps) == 1
        repo.delete_step(step.id)
        assert len(repo.get_steps(s.id)) == 0


class TestFanProgressRepo:
    def test_create_progress(self, repo):
        p = FanSequenceProgress(fan_id="fan_1", sequence_id="seq_1", creator_id="sunny")
        saved = repo.save_progress(p)
        assert saved.id is not None
        assert saved.current_step == 0

    def test_get_progress(self, repo):
        repo.save_progress(FanSequenceProgress(fan_id="fan_1", sequence_id="seq_1", creator_id="sunny"))
        p = repo.get_progress("fan_1", "seq_1", "sunny")
        assert p is not None
        assert p.current_step == 0

    def test_update_progress_advance(self, repo):
        saved = repo.save_progress(FanSequenceProgress(fan_id="fan_1", sequence_id="seq_1", creator_id="sunny"))
        saved.current_step = 2
        saved.status = StepStatus.BOUGHT
        saved.bought_at = datetime.now(timezone.utc)
        repo.save_progress(saved)
        p = repo.get_progress("fan_1", "seq_1", "sunny")
        assert p.current_step == 2
        assert p.status == StepStatus.BOUGHT
        assert p.bought_at is not None

    def test_get_all_progress_for_fan(self, repo):
        repo.save_progress(FanSequenceProgress(fan_id="fan_1", sequence_id="seq_a", creator_id="sunny"))
        repo.save_progress(FanSequenceProgress(fan_id="fan_1", sequence_id="seq_b", creator_id="sunny"))
        all_p = repo.get_fan_progress("fan_1", "sunny")
        assert len(all_p) == 2

    def test_get_active_sequences_for_fan(self, repo):
        """Get sequences that are active and the fan hasn't completed."""
        s = repo.save_sequence(Sequence("Welcome", SequenceTrigger.NEW_SUB, "rapport"))
        repo.save_progress(FanSequenceProgress(fan_id="fan_1", sequence_id=s.id, creator_id="sunny"))
        active = repo.get_active_sequences_for_fan("fan_1", "sunny")
        assert len(active) == 1
        assert active[0].name == "Welcome"

    def test_completed_sequence_not_returned_as_active(self, repo):
        s = repo.save_sequence(Sequence("Done", SequenceTrigger.NEW_SUB, "rapport"))
        p = FanSequenceProgress(fan_id="fan_1", sequence_id=s.id, creator_id="sunny")
        p.status = StepStatus.BOUGHT
        repo.save_progress(p)
        active = repo.get_active_sequences_for_fan("fan_1", "sunny")
        assert len(active) == 0
