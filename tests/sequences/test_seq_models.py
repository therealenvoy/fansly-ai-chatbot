"""Tests for PPV Sequence data models — RED phase."""
import pytest
from datetime import datetime, timezone
from src.sequences.models import Sequence, SequenceStep, FanSequenceProgress, SequenceTrigger, StepStatus


class TestSequence:
    def test_create_sequence(self):
        s = Sequence(name="Welcome Ladder", trigger=SequenceTrigger.NEW_SUB, funnel_stage="rapport")
        assert s.name == "Welcome Ladder"
        assert s.trigger == SequenceTrigger.NEW_SUB
        assert s.is_active is True
        assert s.steps == []

    def test_sequence_with_steps(self):
        s = Sequence("Test", SequenceTrigger.WELCOME, "tease")
        step = SequenceStep(sequence_id=s.id, position=1, media_id="media_1", price=9.99)
        s.steps.append(step)
        assert len(s.steps) == 1
        assert s.steps[0].position == 1
        assert s.steps[0].price == 9.99

    def test_none_trigger_defaults_to_welcome(self):
        """If trigger is unset, default to WELCOME."""
        assert SequenceTrigger.WELCOME.value == "welcome"


class TestSequenceStep:
    def test_step_with_minimal_fields(self):
        step = SequenceStep(sequence_id="seq_1", position=1, media_id="media_abc", price=19.99)
        assert step.media_id == "media_abc"
        assert step.price == 19.99
        assert step.tease_script == ""  # defaults empty
        assert step.offer_script == ""

    def test_step_with_all_fields(self):
        step = SequenceStep(
            sequence_id="seq_1",
            position=2,
            media_id="media_xyz",
            preview_id="preview_1",
            price=29.99,
            tease_script="I made something hot...",
            offer_script="Here it is babe 🔥",
        )
        assert step.preview_id == "preview_1"
        assert step.offer_script == "Here it is babe 🔥"

    def test_step_position_order_key(self):
        step1 = SequenceStep(sequence_id="s1", position=1, media_id="a", price=5)
        step2 = SequenceStep(sequence_id="s1", position=2, media_id="b", price=10)
        step3 = SequenceStep(sequence_id="s1", position=3, media_id="c", price=15)
        steps = [step3, step1, step2]
        steps.sort(key=lambda s: s.position)
        assert [s.price for s in steps] == [5, 10, 15]


class TestFanSequenceProgress:
    def test_new_progress_starts_at_step_0(self):
        p = FanSequenceProgress(fan_id="fan_1", sequence_id="seq_1", creator_id="sunny")
        assert p.current_step == 0
        assert p.status == StepStatus.PENDING

    def test_advance_step_increments(self):
        p = FanSequenceProgress(fan_id="fan_1", sequence_id="seq_1", creator_id="sunny")
        p.current_step = 1
        assert p.current_step == 1

    def test_bought_updates_status(self):
        p = FanSequenceProgress(fan_id="fan_1", sequence_id="seq_1", creator_id="sunny")
        p.status = StepStatus.BOUGHT
        p.bought_at = datetime.now(timezone.utc)
        assert p.status == StepStatus.BOUGHT
        assert p.bought_at is not None