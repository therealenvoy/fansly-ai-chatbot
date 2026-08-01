"""Creator-scoped live instructions for autonomous chat generation."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from .store import SettingsStore


CHAT_INSTRUCTIONS_SETTING = "conversation.chat_instructions"
BRAND_BIBLE_SETTING = "conversation.brand_bible"
MAX_CHAT_INSTRUCTIONS_CHARS = 40_000
MAX_BRAND_BIBLE_CHARS = 20_000


class ChatGuidanceError(ValueError):
    """Safe operator-facing validation error."""


@dataclass(frozen=True)
class ChatGuidanceSnapshot:
    chat_instructions: str
    brand_bible: str


class ChatGuidanceService:
    """Persist and serve the live prompt documents for one creator."""

    def __init__(
        self,
        settings_store: SettingsStore,
        *,
        legacy_brand_bible_path: str | Path | None = None,
    ):
        self.settings_store = settings_store
        self._lock = threading.RLock()
        self._chat_instructions = str(
            settings_store.get_scoped(CHAT_INSTRUCTIONS_SETTING, "") or ""
        ).strip()
        self._brand_bible = str(
            settings_store.get_scoped(BRAND_BIBLE_SETTING, "") or ""
        ).strip()
        if not self._brand_bible and legacy_brand_bible_path is not None:
            legacy_path = Path(legacy_brand_bible_path)
            if legacy_path.exists():
                legacy = legacy_path.read_text(encoding="utf-8").strip()
                if legacy:
                    self._brand_bible = self._validate(
                        legacy,
                        field_name="Brand Bible",
                        maximum=MAX_BRAND_BIBLE_CHARS,
                    )
                    settings_store.set(
                        BRAND_BIBLE_SETTING,
                        self._brand_bible,
                    )

    def snapshot(self) -> ChatGuidanceSnapshot:
        with self._lock:
            return ChatGuidanceSnapshot(
                chat_instructions=self._chat_instructions,
                brand_bible=self._brand_bible,
            )

    def save_chat_instructions(self, value: str) -> ChatGuidanceSnapshot:
        normalized = self._validate(
            value,
            field_name="Chatting instructions",
            maximum=MAX_CHAT_INSTRUCTIONS_CHARS,
        )
        with self._lock:
            self.settings_store.set(
                CHAT_INSTRUCTIONS_SETTING,
                normalized,
            )
            self._chat_instructions = normalized
            return self.snapshot()

    def save_brand_bible(self, value: str) -> ChatGuidanceSnapshot:
        normalized = self._validate(
            value,
            field_name="Brand Bible",
            maximum=MAX_BRAND_BIBLE_CHARS,
        )
        with self._lock:
            self.settings_store.set(
                BRAND_BIBLE_SETTING,
                normalized,
            )
            self._brand_bible = normalized
            return self.snapshot()

    @staticmethod
    def _validate(
        value: str,
        *,
        field_name: str,
        maximum: int,
    ) -> str:
        if not isinstance(value, str):
            raise ChatGuidanceError(f"{field_name} must be text")
        normalized = value.strip()
        if len(normalized) > maximum:
            raise ChatGuidanceError(
                f"{field_name} must be {maximum:,} characters or fewer"
            )
        return normalized
