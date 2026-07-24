"""Objection handling dispatcher — classifies fan objections and routes to handler scripts.

Provides pause/resume flow so the main conversation pipeline can yield
to objection-handling scripts until the objection is resolved.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Keyword-to-type mapping for classify_objection()
# ---------------------------------------------------------------------------
# Ordered from most-specific to least-specific to ensure price patterns
# (e.g. "expensive") are checked before more generic patterns.
_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:too\s+(?:much|expensive|pricey|high)|overpriced|not\s+worth|rip\s*off)\b", "price"),
    (r"\b(?:free|sample|trial|preview|demo|tease)\b", "free_request"),
    (r"\b(?:think\s+about|not\s+sure|maybe|later|undecided|need\s+time|sleep\s+on)\b", "hesitation"),
    (r"\b(?:already\s+(?:bought|paid|got|have|purchased|unlocked))\b", "already_bought"),
]

# Handler script template names for each objection type.
_HANDLER_SCRIPTS: dict[str, str] = {
    "price": "handle_price_objection",
    "free_request": "handle_free_request",
    "hesitation": "handle_hesitation",
    "already_bought": "handle_already_bought",
    "unknown": "handle_unknown_objection",
}


class ObjectionDispatcher:
    """Classifies fan objection messages and routes to appropriate handler scripts.

    Also provides pause/resume flow so the main conversation pipeline can be
    suspended while an objection is being handled.
    """

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify_objection(message: str) -> str:
        """Classify a fan message into an objection type.

        Args:
            message: The fan message string to classify.

        Returns:
            One of ``"price"``, ``"free_request"``, ``"hesitation"``,
            ``"already_bought"``, or ``"unknown"``.
        """
        lower = message.lower()
        for pattern, obj_type in _PATTERNS:
            if re.search(pattern, lower):
                return obj_type
        return "unknown"

    # ------------------------------------------------------------------
    # Handler routing
    # ------------------------------------------------------------------

    @staticmethod
    def get_handler(objection_type: str) -> str:
        """Return the handler script template name for the given objection type.

        Args:
            objection_type: One of the strings returned by
                :meth:`classify_objection`.

        Returns:
            A handler script name such as ``"handle_price_objection"``.
        """
        return _HANDLER_SCRIPTS.get(objection_type, "handle_unknown_objection")

    # ------------------------------------------------------------------
    # Pause / resume main flow
    # ------------------------------------------------------------------

    @staticmethod
    def pause_main_flow(session: Any) -> None:
        """Mark *session* as being in objection-handling mode.

        Sets ``session._objection_mode = True`` so the main conversation
        pipeline knows to yield control.
        """
        session._objection_mode = True  # type: ignore[attr-defined]

    @staticmethod
    def resume_main_flow(session: Any) -> None:
        """Clear the objection-handling flag on *session*."""
        session._objection_mode = False  # type: ignore[attr-defined]

    @staticmethod
    def is_in_objection(session: Any) -> bool:
        """Return ``True`` if the session is currently in objection mode."""
        return bool(getattr(session, "_objection_mode", False))
