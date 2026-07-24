"""Whale Nurture Pipeline.

Detects high-value fans ("whales") through signal analysis of their
messages and fan notes, then routes them through a phased nurture
program culminating in VIP treatment.
"""

import re
from typing import Any


class WhalePipeline:
    """Pipeline for detecting and nurturing whale (high-value) fans.

    Analyses combined signals from message content and fan data
    (tips, purchasing behaviour) to identify potential whales, then
    guides them through rapport → reciprocity → targeted_asks → vip.
    """

    # ── Signal keywords / patterns ────────────────────────────────────

    _JOB_PATTERNS: list[str] = [
        r"\b(engineer|doctor|lawyer|executive|ceo|founder|director|vice president|vp|surgeon|dentist|architect|pilot|pharmacist|cpa|cfo|coo|cto|developer|software|programmer|tech|finance|investment|banker|hedge fund|private equity|consultant|anesthesiologist|orthodontist)\b",
        r"\bmy (job|work|career|salary|business|company|startup|firm|practice|office)\b",
        r"\b(at work|just got off|shift|bonus|paycheck|promotion|overtime)\b",
    ]

    _BIG_TIP_THRESHOLD: float = 50.0

    # ── detect_signals ────────────────────────────────────────────────

    def detect_signals(
        self, messages: list[str], fan_notes: dict[str, Any]
    ) -> list[str]:
        """Scan messages and fan notes for whale signals.

        Args:
            messages: Recent chat messages from the fan.
            fan_notes: Dictionary of fan metadata (total_tips,
                       max_single_tip, purchase_frequency, etc.).

        Returns:
            List of signal strings found (e.g. ``["job_mention", "big_tip"]``).
        """
        signals: list[str] = []

        # Job mention signal
        combined = " ".join(messages).lower()
        if any(re.search(pattern, combined, re.IGNORECASE) for pattern in self._JOB_PATTERNS):
            signals.append("job_mention")

        # Big tip signal
        total_tips = fan_notes.get("total_tips", 0.0)
        max_single = fan_notes.get("max_single_tip", 0.0)
        if total_tips >= self._BIG_TIP_THRESHOLD or max_single >= self._BIG_TIP_THRESHOLD:
            signals.append("big_tip")

        # Rapid purchasing signal
        purchase_freq = fan_notes.get("purchase_frequency")
        if purchase_freq is not None and purchase_freq >= 5:
            signals.append("rapid_purchasing")

        # Custom request signal
        custom_count = fan_notes.get("custom_requests", 0)
        if custom_count >= 1:
            signals.append("custom_request")

        # Personal sharing signal
        personal_keywords = [
            r"\b(personal|private|just between us|don't tell anyone|secret|confession|trust you|close to you|comfortable with you|opening up)\b",
            r"\b(my (life|story|past|childhood|marriage|divorce|ex[- ](husband|wife|girlfriend|boyfriend)|family|kids|children))\b",
        ]
        if any(re.search(kw, combined, re.IGNORECASE) for kw in personal_keywords):
            signals.append("personal_sharing")

        return signals

    # ── is_potential_whale ────────────────────────────────────────────

    def is_potential_whale(self, signals: list[str]) -> bool:
        """Return True when 2+ whale signals have been detected.

        Args:
            signals: List of signal strings from :meth:`detect_signals`.

        Returns:
            True if the fan qualifies as a potential whale.
        """
        return len(signals) >= 2

    # ── nurture_phase ─────────────────────────────────────────────────

    def nurture_phase(self, fan_id: str, days_since_first_contact: int) -> str:
        """Determine the current nurture phase for a fan.

        Phases:
            * **rapport**      — days 0–13  (build trust, casual chat)
            * **reciprocity**  — days 14–29 (soft asks, freebie→premium)
            * **targeted_asks** — days 30–59 (personalised PPV pitches)
            * **vip**          — days 60+   (white-glove treatment)

        Args:
            fan_id: The fan's unique identifier.
            days_since_first_contact: Number of days since first interaction.

        Returns:
            Phase name string.
        """
        if days_since_first_contact < 14:
            return "rapport"
        elif days_since_first_contact < 30:
            return "reciprocity"
        elif days_since_first_contact < 60:
            return "targeted_asks"
        else:
            return "vip"

    # ── vip_treatment ─────────────────────────────────────────────────

    def vip_treatment(self, fan_id: str) -> dict[str, bool]:
        """Return the VIP treatment configuration for a fan.

        Args:
            fan_id: The fan's unique identifier.

        Returns:
            Dict with all VIP flags set to ``True``.
        """
        return {
            "priority_response": True,
            "exclusive_content": True,
            "premium_pricing": True,
            "dedicated_chatter": True,
        }
