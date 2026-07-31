"""Bounded operator control for one-time unanswered-chat recovery."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Callable, ContextManager

from .bot import FanslyBot
from .persistence.state import ConversationStateRepository


logger = logging.getLogger(__name__)


class UnreadBacklogError(RuntimeError):
    """Raised when the bounded backlog import cannot start safely."""


class UnreadBacklogController:
    """Persist progress and run one operator-approved batch at a time."""

    SCOPE = "apifansly-unanswered-backlog:v2"
    MAX_BATCH_CHATS = 5

    def __init__(
        self,
        *,
        bot: FanslyBot | None,
        state_repo: ConversationStateRepository,
        creator_id: str | None = None,
        inbound_wakeup=None,
        guard_factory: Callable[[], ContextManager] | None = None,
    ):
        self.bot = bot
        self.state_repo = state_repo
        resolved_creator_id = creator_id or getattr(bot, "creator_id", None)
        self.creator_id = (
            resolved_creator_id.strip()
            if isinstance(resolved_creator_id, str)
            and resolved_creator_id.strip()
            else "unavailable"
        )
        self.inbound_wakeup = inbound_wakeup
        self.guard_factory = guard_factory or nullcontext
        self._lock = threading.Lock()
        state = self._load()
        if state.get("phase") == "running":
            state.update(
                {
                    "phase": "interrupted",
                    "last_error_code": "RuntimeRestarted",
                    "updated_at": self._now(),
                }
            )
            self._save(state)

    def snapshot(self) -> dict:
        with self._lock:
            state = self._load()
        available, reason = self._availability()
        phase = str(state.get("phase") or "not_started")
        return {
            "available": available,
            "reason": reason,
            "phase": phase,
            "running": phase == "running",
            "batch_limit": self.MAX_BATCH_CHATS,
            "processed_chats": int(state.get("processed_chats") or 0),
            "queued_inbound": int(state.get("queued_inbound") or 0),
            "skipped_chats": int(state.get("skipped_chats") or 0),
            "batches_completed": int(state.get("batches_completed") or 0),
            "last_batch_processed": int(
                state.get("last_batch_processed") or 0
            ),
            "last_batch_queued": int(
                state.get("last_batch_queued") or 0
            ),
            "last_error_code": state.get("last_error_code"),
            "updated_at": state.get("updated_at"),
            "webhook_first": True,
            "automatic_polling": False,
            "sends_from_control": False,
            "requires_review_between_batches": True,
        }

    def start(self, *, max_chats: int = MAX_BATCH_CHATS) -> dict:
        available, reason = self._availability()
        if not available:
            raise UnreadBacklogError(reason)
        requested = int(max_chats)
        if requested < 1 or requested > self.MAX_BATCH_CHATS:
            raise UnreadBacklogError(
                f"Batch size must be between 1 and {self.MAX_BATCH_CHATS}"
            )
        with self._lock:
            state = self._load()
            if state.get("phase") == "running":
                raise UnreadBacklogError(
                    "An unanswered backlog batch is running"
                )
            state.update(
                {
                    "phase": "running",
                    "last_error_code": None,
                    "updated_at": self._now(),
                }
            )
            self._save(state)
            worker = threading.Thread(
                target=self._run,
                args=(requested,),
                name="unread-backlog-batch",
                daemon=True,
            )
            worker.start()
        return self.snapshot()

    def _run(self, max_chats: int) -> None:
        try:
            with self._lock:
                state = self._load()
                cursor = state.get("provider_cursor")
            with self.guard_factory():
                result = self.bot.import_unread_backlog_batch(
                    cursor=(str(cursor) if cursor else None),
                    max_chats=max_chats,
                )
            with self._lock:
                state = self._load()
                previous_cursor = state.get("provider_cursor")
                if (
                    not result.exhausted
                    and result.next_cursor
                    and result.next_cursor == previous_cursor
                    and result.processed_chats == 0
                ):
                    raise UnreadBacklogError(
                        "Provider chat cursor did not advance"
                    )
                state.update(
                    {
                        "phase": (
                            "complete"
                            if result.exhausted
                            else "awaiting_review"
                        ),
                        "provider_cursor": result.next_cursor,
                        "processed_chats": int(
                            state.get("processed_chats") or 0
                        )
                        + result.processed_chats,
                        "queued_inbound": int(
                            state.get("queued_inbound") or 0
                        )
                        + result.queued_inbound,
                        "skipped_chats": int(
                            state.get("skipped_chats") or 0
                        )
                        + result.skipped_chats,
                        "batches_completed": int(
                            state.get("batches_completed") or 0
                        )
                        + 1,
                        "last_batch_processed": result.processed_chats,
                        "last_batch_queued": result.queued_inbound,
                        "last_error_code": None,
                        "updated_at": self._now(),
                    }
                )
                self._save(state)
            if result.queued_inbound and self.inbound_wakeup is not None:
                self.inbound_wakeup.set()
            logger.info(
                "Unanswered backlog batch finished: processed=%s queued=%s "
                "skipped=%s",
                result.processed_chats,
                result.queued_inbound,
                result.skipped_chats,
            )
        except Exception as error:
            with self._lock:
                state = self._load()
                state.update(
                    {
                        "phase": "failed",
                        "last_error_code": type(error).__name__,
                        "updated_at": self._now(),
                    }
                )
                self._save(state)
            logger.error(
                "Unanswered backlog batch failed safely: %s",
                type(error).__name__,
            )

    def _availability(self) -> tuple[bool, str | None]:
        if self.bot is None:
            return False, "Bot runtime is unavailable"
        if not self.bot.enabled:
            return False, "Bot is disabled"
        if not self.bot.enable_unread_replies:
            return False, "Unread replies are disabled"
        method = getattr(self.bot.client, "list_chats_page", None)
        if not callable(method):
            return False, "Provider cannot list recent chats"
        return True, None

    def _load(self) -> dict:
        raw = self.state_repo.get_poll_cursor(
            self.creator_id,
            self.SCOPE,
        )
        if not raw:
            return self._default_state()
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            return self._default_state()
        return state if isinstance(state, dict) else self._default_state()

    def _save(self, state: dict) -> None:
        self.state_repo.set_poll_cursor(
            self.creator_id,
            self.SCOPE,
            json.dumps(state, separators=(",", ":"), sort_keys=True),
        )

    @staticmethod
    def _default_state() -> dict:
        return {
            "phase": "not_started",
            "provider_cursor": None,
            "processed_chats": 0,
            "queued_inbound": 0,
            "skipped_chats": 0,
            "batches_completed": 0,
            "last_batch_processed": 0,
            "last_batch_queued": 0,
            "last_error_code": None,
            "updated_at": None,
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
