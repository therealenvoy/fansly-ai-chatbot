"""PPV Sequence data models.

A Sequence is an ordered ladder of PPV content items from the creator's vault.
The bot progresses fans through the sequence as they buy each step.

Sequence  → has many → SequenceStep
Fan       → may have → FanSequenceProgress (per sequence)
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class SequenceTrigger(str, Enum):
    """What event triggers this sequence to become active for a fan."""
    NEW_SUB = "new_sub"         # First subscription
    WELCOME = "welcome"         # First DM after subscribe
    RAPPORT = "rapport"         # After rapport stage in funnel
    WHALE = "whale"             # Detected high-value fan
    RE_ENGAGE = "re_engage"     # Churn risk recovery
    MANUAL = "manual"           # Only sent manually via dashboard


class StepStatus(str, Enum):
    """Status of a fan's progress through a single step."""
    PENDING = "pending"         # Not yet sent
    SENT = "sent"               # Tease/offer sent, awaiting response
    BOUGHT = "bought"           # Fan purchased
    SKIPPED = "skipped"         # Fan declined, move to next
    LOCKED = "locked"           # Behind a step that hasn't been bought yet


@dataclass
class SequenceStep:
    """A single PPV item in a sequence, at a specific position."""
    sequence_id: str
    position: int
    media_id: str
    price: float
    id: Optional[str] = None
    preview_id: Optional[str] = None
    tease_script: str = ""      # What the bot says before sending PPV
    offer_script: str = ""       # What the bot says when sending the PPV
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Sequence:
    """A named ordered ladder of PPV content items."""
    name: str
    trigger: SequenceTrigger
    funnel_stage: str = "rapport"  # Which funnel stage this targets
    id: Optional[str] = None
    is_active: bool = True
    steps: list[SequenceStep] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def total_price(self) -> float:
        return sum(s.price for s in self.steps)

    def step_count(self) -> int:
        return len(self.steps)

    def get_step(self, position: int) -> Optional[SequenceStep]:
        for s in self.steps:
            if s.position == position:
                return s
        return None


@dataclass
class FanSequenceProgress:
    """Tracks a specific fan's progress through a specific sequence."""
    fan_id: str
    sequence_id: str
    creator_id: str
    id: Optional[str] = None
    current_step: int = 0  # 0 = not started, 1+ = step position
    status: StepStatus = StepStatus.PENDING
    last_sent_at: Optional[datetime] = None
    bought_at: Optional[datetime] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_complete(self) -> bool:
        return self.status == StepStatus.BOUGHT and self.current_step == 0

    def advance(self):
        self.current_step += 1
        self.status = StepStatus.PENDING