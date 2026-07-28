"""Sequence Engine — orchestrates PPV sequence progression for each fan.

When a fan reaches a funnel stage, the engine:
1. Finds active sequences matching the fan's stage/trigger
2. Checks the fan's progress in each sequence
3. Returns the next unsent PPV step (tease + offer scripts + media)
4. Tracks sends and purchases to advance the fan

Integrates with the bot's _generate_reply and _send_premium_ppv methods.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from .models import (
    Sequence, SequenceStep, FanSequenceProgress,
    SequenceTrigger, StepStatus,
)
from .repository import SequenceRepository

logger = logging.getLogger(__name__)


class SequenceEngine:
    """Stateless engine that queries sequence/progress state and returns next actions."""

    def __init__(self, repo: SequenceRepository, creator_id: str):
        self.repo = repo
        self.creator_id = creator_id

    def get_next_ppv(
        self, fan_id: str, funnel_stage: str, fan_total_spent: float = 0.0
    ) -> Optional[tuple[Sequence, SequenceStep]]:
        """Get the next PPV to send for a fan.

        current_step tracks the next step to serve:
        - 0 = not started (serve step 1)
        - N = serve step N
        Returns (sequence, step) or None if nothing is due.
        """
        active_seqs = self.repo.get_active_sequences_for_fan(fan_id, self.creator_id)
        if not active_seqs:
            return None

        # Filter sequences by funnel stage match
        matching = [s for s in active_seqs if s.funnel_stage == funnel_stage]
        if not matching:
            matching = active_seqs

        if not matching:
            return None

        scored = []
        for seq in matching:
            progress = self.repo.get_progress(fan_id, seq.id, self.creator_id)
            score = self._score_sequence(seq, progress, fan_total_spent)
            scored.append((score, seq, progress))

        scored.sort(key=lambda x: x[0], reverse=True)
        _, best_seq, best_progress = scored[0]

        # Determine next step position
        next_pos = best_progress.current_step if best_progress else 1
        if next_pos == 0:  # sentinel: complete
            return None

        next_step = best_seq.get_step(next_pos)
        if not next_step:
            return None

        return best_seq, next_step

    def _score_sequence(
        self,
        seq: Sequence,
        progress: Optional[FanSequenceProgress],
        fan_total_spent: float,
    ) -> int:
        """Score a sequence's relevance for a fan. Higher = better match."""
        score = 0

        # Prefer sequences where the fan hasn't started yet
        if progress is None:
            score += 10

        # Prefer trigger-matched sequences
        if seq.trigger == SequenceTrigger.NEW_SUB:
            score += 5
        elif seq.trigger == SequenceTrigger.WHALE and fan_total_spent > 100:
            score += 8
        elif seq.trigger == SequenceTrigger.RE_ENGAGE:
            score += 3

        # Prefer sequences with more steps (longer ladders = more revenue)
        score += min(seq.step_count(), 5)

        return score

    def mark_sent(self, fan_id: str, sequence: Sequence, step: SequenceStep):
        """Record that a PPV step was sent. Advances current_step to next position."""
        next_pos = step.position + 1
        progress = self.repo.get_progress(fan_id, sequence.id, self.creator_id)
        if progress is None:
            progress = FanSequenceProgress(
                fan_id=fan_id,
                sequence_id=sequence.id,
                creator_id=self.creator_id,
                current_step=next_pos,
                status=StepStatus.SENT,
                last_sent_at=datetime.now(timezone.utc),
            )
        else:
            progress.current_step = next_pos
            progress.status = StepStatus.SENT
            progress.last_sent_at = datetime.now(timezone.utc)

        self.repo.save_progress(progress)
        logger.info(
            "PPV step marked sent: position=%s sequence_id=%s",
            step.position,
            sequence.id,
        )

    def mark_purchased(self, fan_id: str, sequence_id: int):
        """Mark current step as bought. Advance to next step if one exists."""
        progress = self.repo.get_progress(fan_id, sequence_id, self.creator_id)
        if not progress:
            return

        seq = self.repo.get_sequence(sequence_id)
        if not seq:
            return

        # The step the fan bought was at position (current_step - 1)
        bought_pos = progress.current_step - 1
        if bought_pos < 1:
            return  # safety

        progress.status = StepStatus.BOUGHT
        progress.bought_at = datetime.now(timezone.utc)

        # Advance to next step if one exists
        next_step = seq.get_step(progress.current_step)  # current_step already points to next
        if next_step:
            # current_step already IS the next position (set by mark_sent)
            progress.status = StepStatus.PENDING  # Ready to be teased for next PPV
        else:
            # No more steps — sequence complete
            progress.current_step = 0  # sentinel: 0 = complete

        self.repo.save_progress(progress)
        logger.info(
            "PPV purchase attributed: step=%s sequence_id=%s next_step=%s",
            bought_pos,
            sequence_id,
            progress.current_step if next_step else "COMPLETE",
        )

    def mark_skipped(self, fan_id: str, sequence_id: int):
        """Mark current PPV as skipped (fan declined). The engine naturally serves current_step + 1 next."""
        progress = self.repo.get_progress(fan_id, sequence_id, self.creator_id)
        if not progress:
            return

        seq = self.repo.get_sequence(sequence_id)
        if not seq:
            return

        progress.status = StepStatus.SKIPPED
        # Don't advance current_step — get_next_ppv will serve current_step + 1
        self.repo.save_progress(progress)
        logger.info(
            "PPV step skipped: step=%s sequence_id=%s",
            progress.current_step,
            sequence_id,
        )

    def get_active_tease_for_fan(self, fan_id: str, funnel_stage: str) -> Optional[str]:
        """Get the tease script for the next PPV the fan is due for."""
        result = self.get_next_ppv(fan_id, funnel_stage)
        if not result:
            return None
        seq, step = result
        return step.tease_script or f"I made something just for you... want to see what I've been working on? 😏"
