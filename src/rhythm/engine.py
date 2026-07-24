"""Push-Pull Rhythm Engine.

Alternates between normal conversation (PULL) and flirtatious spikes (PUSH).
After a push, steps back and detects when the fan steers back to sexual territory.
"""

from dataclasses import dataclass, field
from enum import Enum


class RhythmPhase(str, Enum):
    """The two phases of the push-pull rhythm."""

    PULL = "pull"
    PUSH = "push"


# Keywords that suggest fan is steering toward sexual territory.
PUSH_INDICATORS: list[str] = [
    "what are you wearing",
    "send me",
    "show me",
    "can i see",
    "you're so hot",
    "i want to see",
    "what would you do",
    "tell me more",
    "i'm so turned on",
    "you make me",
]


@dataclass
class FanMessageAnalysis:
    """Result of analyzing a fan message for push-pull rhythm detection.

    Attributes:
        fan_initiated: True if the fan's message contains PUSH_INDICATORS.
        ready_for_tease: True only when fan_initiated AND the current phase is PUSH.
        detected_indicators: Which specific indicators were found in the message.
    """

    fan_initiated: bool
    ready_for_tease: bool
    detected_indicators: list[str]


class PushPullEngine:
    """Engine that tracks push-pull rhythm state.

    Attributes:
        phase_history: Ordered list of all phases, starting with PULL.
        push_count: Number of times the engine entered PUSH phase.
        pull_count: Number of times the engine entered PULL phase.
    """

    def __init__(self) -> None:
        self.phase_history: list[RhythmPhase] = [RhythmPhase.PULL]
        self.push_count: int = 0
        self.pull_count: int = 0

    @property
    def current_phase(self) -> RhythmPhase:
        """The current rhythm phase (last entry in history)."""
        return self.phase_history[-1]

    def next(self) -> None:
        """Toggle between PULL→PUSH or PUSH→PULL, incrementing the appropriate counter."""
        new_phase = RhythmPhase.PUSH if self.current_phase == RhythmPhase.PULL else RhythmPhase.PULL
        self.phase_history.append(new_phase)
        if new_phase == RhythmPhase.PUSH:
            self.push_count += 1
        else:
            self.pull_count += 1

    def force_push(self) -> None:
        """Force a transition to PUSH. Only works when currently in PULL.

        Raises:
            ValueError: If the engine is already in PUSH phase.
        """
        if self.current_phase == RhythmPhase.PUSH:
            raise ValueError("Cannot force_push: already in PUSH phase")
        self.phase_history.append(RhythmPhase.PUSH)
        self.push_count += 1

    def analyze_fan_message(self, message: str) -> FanMessageAnalysis:
        """Analyze a fan message for push indicators.

        Args:
            message: The fan's chat message (case-insensitive matching).

        Returns:
            FanMessageAnalysis with detected indicators and ready_for_tease
            computed based on the current rhythm phase.
        """
        message_lower = message.lower()
        detected: list[str] = [
            indicator
            for indicator in PUSH_INDICATORS
            if indicator in message_lower
        ]
        fan_initiated = len(detected) > 0
        ready_for_tease = fan_initiated and self.current_phase == RhythmPhase.PUSH
        return FanMessageAnalysis(
            fan_initiated=fan_initiated,
            ready_for_tease=ready_for_tease,
            detected_indicators=detected,
        )