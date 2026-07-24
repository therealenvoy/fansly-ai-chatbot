"""Tests for the Push-Pull Rhythm Engine."""

import pytest

from src.rhythm.engine import FanMessageAnalysis, PushPullEngine, RhythmPhase


class TestRhythmPhase:
    """Tests for the RhythmPhase enum."""

    def test_phases_exist(self):
        """RhythmPhase should have PULL and PUSH members."""
        assert RhythmPhase.PULL.value == "pull"
        assert RhythmPhase.PUSH.value == "push"


class TestFanMessageAnalysis:
    """Tests for the FanMessageAnalysis dataclass."""

    def test_analysis_creation(self):
        """Should create analysis with default values."""
        analysis = FanMessageAnalysis(
            fan_initiated=True,
            ready_for_tease=False,
            detected_indicators=["what are you wearing"],
        )
        assert analysis.fan_initiated is True
        assert analysis.ready_for_tease is False
        assert analysis.detected_indicators == ["what are you wearing"]

    def test_analysis_empty_indicators(self):
        """Should work with empty indicators list."""
        analysis = FanMessageAnalysis(
            fan_initiated=False,
            ready_for_tease=False,
            detected_indicators=[],
        )
        assert analysis.detected_indicators == []


class TestPushPullEngine:
    """Tests for the PushPullEngine class."""

    def test_starts_in_pull_phase(self):
        """A new engine should start in PULL phase."""
        engine = PushPullEngine()
        assert engine.current_phase == RhythmPhase.PULL
        assert engine.push_count == 0
        assert engine.pull_count == 0

    def test_alternates_push_pull(self):
        """Calling next() twice should go PULL → PUSH → PULL."""
        engine = PushPullEngine()
        assert engine.current_phase == RhythmPhase.PULL

        engine.next()
        assert engine.current_phase == RhythmPhase.PUSH

        engine.next()
        assert engine.current_phase == RhythmPhase.PULL

    def test_cannot_push_twice_in_a_row(self):
        """force_push() should raise ValueError if already in PUSH phase."""
        engine = PushPullEngine()
        # First, move to PUSH
        engine.next()
        assert engine.current_phase == RhythmPhase.PUSH

        with pytest.raises(ValueError):
            engine.force_push()

    def test_detect_fan_initiated_return(self):
        """Message with 'what are you wearing' → fan_initiated=True, ready_for_tease=True (if in PUSH)."""
        engine = PushPullEngine()
        # Move to PUSH phase
        engine.next()
        assert engine.current_phase == RhythmPhase.PUSH

        analysis = engine.analyze_fan_message("what are you wearing")
        assert analysis.fan_initiated is True
        assert analysis.ready_for_tease is True
        assert "what are you wearing" in analysis.detected_indicators

    def test_fan_ignores_push_stays_in_push(self):
        """Message about 'how was your day' → fan_initiated=False, ready_for_tease=False."""
        engine = PushPullEngine()
        engine.next()  # PUSH phase
        assert engine.current_phase == RhythmPhase.PUSH

        analysis = engine.analyze_fan_message("how was your day")
        assert analysis.fan_initiated is False
        assert analysis.ready_for_tease is False
        assert analysis.detected_indicators == []

    def test_pull_phase_no_tease_ready(self):
        """Even with indicators, ready_for_tease=False when current is PULL."""
        engine = PushPullEngine()
        assert engine.current_phase == RhythmPhase.PULL

        analysis = engine.analyze_fan_message("what are you wearing")
        assert analysis.fan_initiated is True
        assert analysis.ready_for_tease is False
        assert "what are you wearing" in analysis.detected_indicators

    def test_push_pull_counters(self):
        """Counters should increment correctly."""
        engine = PushPullEngine()
        assert engine.push_count == 0
        assert engine.pull_count == 0

        engine.next()  # PUSH
        assert engine.push_count == 1
        assert engine.pull_count == 0

        engine.next()  # PULL
        assert engine.push_count == 1
        assert engine.pull_count == 1

        engine.next()  # PUSH
        assert engine.push_count == 2
        assert engine.pull_count == 1

    def test_force_push_from_pull(self):
        """force_push() from PULL should work and increment push_count."""
        engine = PushPullEngine()
        assert engine.current_phase == RhythmPhase.PULL

        engine.force_push()
        assert engine.current_phase == RhythmPhase.PUSH
        assert engine.push_count == 1

    def test_phase_history_is_tracked(self):
        """Phase history should record all phase transitions."""
        engine = PushPullEngine()
        assert engine.phase_history == [RhythmPhase.PULL]

        engine.next()  # PUSH
        assert engine.phase_history == [RhythmPhase.PULL, RhythmPhase.PUSH]

        engine.next()  # PULL
        assert engine.phase_history == [
            RhythmPhase.PULL,
            RhythmPhase.PUSH,
            RhythmPhase.PULL,
        ]

    def test_multiple_push_indicators_detected(self):
        """Should detect multiple indicators in a single message."""
        engine = PushPullEngine()
        engine.next()  # PUSH

        analysis = engine.analyze_fan_message(
            "you're so hot, what are you wearing, send me something"
        )
        assert analysis.fan_initiated is True
        assert analysis.ready_for_tease is True
        assert "you're so hot" in analysis.detected_indicators
        assert "what are you wearing" in analysis.detected_indicators
        assert "send me" in analysis.detected_indicators