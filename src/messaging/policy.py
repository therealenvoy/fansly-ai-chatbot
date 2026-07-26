"""Content gates applied before response generation and outbox insertion."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class PolicyDecision:
    approved: bool
    content: str
    reason: str | None = None


class MessageContentPolicy:
    """Small, deterministic safety boundary around the decision engine."""

    def __init__(
        self,
        *,
        max_inbound_chars: int = 10_000,
        max_outbound_chars: int = 5_000,
    ):
        self.max_inbound_chars = max_inbound_chars
        self.max_outbound_chars = max_outbound_chars

    def validate_inbound(self, content: str) -> PolicyDecision:
        return self._validate(
            content,
            max_chars=self.max_inbound_chars,
            direction="inbound",
        )

    def validate_outbound(self, content: str) -> PolicyDecision:
        return self._validate(
            content,
            max_chars=self.max_outbound_chars,
            direction="outbound",
        )

    @staticmethod
    def _contains_forbidden_control(content: str) -> bool:
        for char in content:
            category = unicodedata.category(char)
            if category == "Cc" and char not in {"\n", "\r", "\t"}:
                return True
        return False

    def _validate(
        self,
        content: str,
        *,
        max_chars: int,
        direction: str,
    ) -> PolicyDecision:
        if not isinstance(content, str):
            return PolicyDecision(
                False,
                "",
                f"{direction} content must be text",
            )
        normalized = content.replace("\r\n", "\n").strip()
        if not normalized:
            return PolicyDecision(
                False,
                "",
                f"{direction} content is empty",
            )
        if len(normalized) > max_chars:
            return PolicyDecision(
                False,
                "",
                f"{direction} content exceeds {max_chars} characters",
            )
        if self._contains_forbidden_control(normalized):
            return PolicyDecision(
                False,
                "",
                f"{direction} content contains control characters",
            )
        return PolicyDecision(True, normalized)
