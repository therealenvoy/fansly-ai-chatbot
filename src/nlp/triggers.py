"""NLPTriggerEngine — NLP trigger generation, command embedding, and anchoring."""

from __future__ import annotations

import random
from typing import Any


class NLPTriggerEngine:
    """Generate NLP-triggered messages, embed commands, and manage anchors.

    Anchors associate positive trigger events with fan_ids to enable
    future NLP conditioning.
    """

    def __init__(self) -> None:
        self._anchors: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Thought-of-you generation
    # ------------------------------------------------------------------

    def generate_thought_of_you(self, fan_notes: dict[str, Any]) -> str | None:
        """Craft a "thinking of you" message referencing a fan interest/hobby.

        Returns None if no interests or hobbies are present in fan_notes.
        """
        interests: list[str] = fan_notes.get("interests", [])
        hobbies: list[str] = fan_notes.get("hobbies", [])
        combined: list[str] = interests + hobbies

        if not combined:
            return None

        topic = random.choice(combined)
        templates = [
            f"I was just thinking about you — remembered how much you love {topic}. Hope you're having an amazing day! 💕",
            f"Something came up today that made me think of you... your passion for {topic} always makes me smile 😊",
            f"Hey! I saw something about {topic} earlier and immediately thought of you. Missing our chats! ❤️",
            f"Just wanted to say hi! Every time {topic} comes up, you pop into my mind. How are things? 🌸",
        ]
        return random.choice(templates)

    # ------------------------------------------------------------------
    # Command embedding
    # ------------------------------------------------------------------

    def embed_command(self, base_message: str, command: str) -> str:
        """Insert a command token into a message naturally.

        The command is appended as a natural continuation of the message.
        """
        connectors = [
            "Oh, and by the way,",
            "Also,",
            "Speaking of which,",
            "On a related note,",
        ]
        connector = random.choice(connectors)
        return f"{base_message} {connector} {command}"

    # ------------------------------------------------------------------
    # Anchoring
    # ------------------------------------------------------------------

    def anchor_positive(self, fan_id: str, trigger_event: str) -> None:
        """Record a positive trigger event for a fan."""
        self._anchors.setdefault(fan_id, []).append(trigger_event)

    def get_anchors(self, fan_id: str) -> list[str]:
        """Return the list of recorded anchor events for a fan.

        Returns an empty list if no anchors exist for the fan_id.
        """
        return list(self._anchors.get(fan_id, []))

    # ------------------------------------------------------------------
    # Trigger-opportunity detection
    # ------------------------------------------------------------------

    def detect_trigger_opportunity(
        self, message: str, fan_notes: dict[str, Any]
    ) -> list[str]:
        """Determine which NLP techniques are applicable.

        Currently detects:
        - "thought_of_you": fan_notes has interests or hobbies
        """
        opportunities: list[str] = []
        if fan_notes.get("interests") or fan_notes.get("hobbies"):
            opportunities.append("thought_of_you")
        return opportunities
