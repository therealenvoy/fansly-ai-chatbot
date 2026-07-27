"""Runtime modes and hard conversation-only delivery policy."""

from __future__ import annotations

from enum import Enum
import re


class BotMode(str, Enum):
    """Explicit operating modes with different launch requirements."""

    CONVERSATION = "conversation"
    FULL_PPV = "full_ppv"

    @classmethod
    def parse(cls, value: str | "BotMode") -> "BotMode":
        if isinstance(value, cls):
            return value
        normalized = str(value or "").strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"BOT_MODE must be one of: {allowed}"
            ) from exc


class ConversationPolicy:
    """Fail closed when a conversation-only response contains sales intent."""

    _SALES_PATTERNS = (
        re.compile(r"\bppv\b", re.IGNORECASE),
        re.compile(r"\bpay[\s-]?per[\s-]?view\b", re.IGNORECASE),
        re.compile(r"\bunlock(?:ed|ing)?\b", re.IGNORECASE),
        re.compile(r"\b(?:buy|purchase|checkout)\b", re.IGNORECASE),
        re.compile(r"\b(?:price|priced|pricing)\b", re.IGNORECASE),
        re.compile(r"\btip\s+(?:me|to|for)\b", re.IGNORECASE),
        re.compile(r"\bpaid\s+(?:message|video|photo|content)\b", re.IGNORECASE),
        re.compile(r"\b(?:subscribe|subscription)\b", re.IGNORECASE),
        re.compile(r"\b(?:want|wanna)\s+to\s+see\b", re.IGNORECASE),
        re.compile(r"\bcheck\s+it\s+out\b", re.IGNORECASE),
        re.compile(
            r"\b(?:made|have|got|saved)\b.{0,40}"
            r"\b(?:video|photo|pic|content|something)\b.{0,30}"
            r"\b(?:for\s+you|show\s+you|see)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\$\s*\d+(?:\.\d{1,2})?\b"),
    )

    def sales_reason(self, content: str) -> str | None:
        for pattern in self._SALES_PATTERNS:
            if pattern.search(content or ""):
                return "conversation mode blocks sales and PPV language"
        return None
