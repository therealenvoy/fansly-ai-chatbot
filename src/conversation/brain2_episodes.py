"""Asynchronous, evidence-bound summaries for older conversation history."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import logging
import re
import threading

from src.conversation.brain2_repository import ConversationEpisodeRepository


logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]{2,}")
_STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "have",
    "how",
    "just",
    "like",
    "that",
    "the",
    "this",
    "was",
    "what",
    "when",
    "with",
    "you",
    "your",
}


def _message_key(message: dict) -> str:
    return str(message.get("message_id") or message.get("id") or "unknown")


def _timestamp(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class EvidenceBoundEpisodeSummarizer:
    """Build structured summaries using only exact source excerpts."""

    def summarize(self, messages: list[dict]) -> dict:
        if not messages:
            raise ValueError("episode_requires_messages")
        texts = [str(item.get("content") or "").strip() for item in messages]
        topic_counts = Counter(
            token.casefold()
            for text in texts
            for token in _WORD.findall(text)
            if token.casefold() not in _STOPWORDS
        )
        topics = [
            token
            for token, _count in sorted(
                topic_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:5]
        ]
        positive = sum(
            marker in text.casefold()
            for text in texts
            for marker in ("happy", "good", "great", "love", "excited")
        )
        negative = sum(
            marker in text.casefold()
            for text in texts
            for marker in ("sad", "tired", "bad", "angry", "upset", "hurt")
        )
        emotional_tone = (
            "mixed"
            if positive and negative
            else "positive"
            if positive
            else "negative"
            if negative
            else "neutral"
        )
        fan_disclosures = self._exact_matches(
            messages,
            sender="fan",
            markers=("i ", "i'm ", "im ", "my ", "i’ve ", "i've "),
        )
        creator_statements = self._exact_matches(
            messages,
            sender="creator",
            markers=("i will ", "i'll ", "i promise ", "we can "),
        )
        boundaries = self._exact_matches(
            messages,
            sender=None,
            markers=(
                "stop ",
                "don't ",
                "do not ",
                "no more",
                "leave me alone",
                "not comfortable",
            ),
        )
        unresolved = [
            text
            for message, text in zip(messages, texts)
            if text and "?" in text and message.get("sender") == "creator"
        ][-3:]
        resolved = [
            text
            for text in texts
            if text
            and any(
                marker in text.casefold()
                for marker in ("got it", "understood", "makes sense", "thank")
            )
        ][-3:]
        callback_source = (
            fan_disclosures[-1]
            if fan_disclosures
            else unresolved[-1]
            if unresolved
            else None
        )
        return {
            "main_topics": topics,
            "emotional_tone": emotional_tone,
            "fan_disclosures": fan_disclosures[-5:],
            "creator_statements": creator_statements[-5:],
            "boundaries": boundaries[-5:],
            "resolved_threads": resolved,
            "unresolved_threads": unresolved,
            "future_callback": (
                f"Revisit: {callback_source}" if callback_source else None
            ),
        }

    @staticmethod
    def _exact_matches(
        messages: list[dict],
        *,
        sender: str | None,
        markers: tuple[str, ...],
    ) -> list[str]:
        matches: list[str] = []
        for message in messages:
            if sender is not None and message.get("sender") != sender:
                continue
            text = str(message.get("content") or "").strip()
            lowered = text.casefold()
            if text and any(
                lowered.startswith(marker) or marker in lowered
                for marker in markers
            ):
                matches.append(text[:500])
        return matches


class ConversationEpisodeService:
    """Generate idempotent older-history episodes outside the reply path."""

    def __init__(
        self,
        *,
        creator_id: str,
        message_store,
        repository: ConversationEpisodeRepository,
        summarizer: EvidenceBoundEpisodeSummarizer | None = None,
        recent_keep: int = 30,
        episode_size: int = 40,
        max_workers: int = 1,
    ):
        self.creator_id = creator_id
        self.message_store = message_store
        self.repository = repository
        self.summarizer = summarizer or EvidenceBoundEpisodeSummarizer()
        self.recent_keep = max(2, int(recent_keep))
        self.episode_size = min(max(2, int(episode_size)), 100)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 2)),
            thread_name_prefix="brain-episodes",
        )
        self._futures: set[Future] = set()
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, fan_id: str) -> bool:
        fan_id = str(fan_id).strip()
        if not fan_id:
            return False
        with self._lock:
            if fan_id in self._inflight:
                return False
            self._inflight.add(fan_id)
        future = self._executor.submit(self._process, fan_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(
            lambda completed, target=fan_id: self._complete(target, completed)
        )
        return True

    def _process(self, fan_id: str) -> None:
        try:
            page = self.message_store.get_history_page(
                fan_id,
                self.creator_id,
                limit=self.episode_size,
                offset=self.recent_keep,
            )
            messages = list(page.messages)
            if len(messages) < 2:
                return
            first = messages[0]
            last = messages[-1]
            start_key = _message_key(first)
            end_key = _message_key(last)
            digest = hashlib.sha256(
                (
                    f"{self.creator_id}:{fan_id}:"
                    f"{start_key}:{end_key}"
                ).encode()
            ).hexdigest()[:24]
            summary = self.summarizer.summarize(messages)
            self.repository.save(
                creator_id=self.creator_id,
                fan_id=fan_id,
                episode_key=f"episode:{digest}",
                **summary,
                source_start_message_id=start_key,
                source_end_message_id=end_key,
                episode_started_at=_timestamp(first["created_at"]),
                episode_ended_at=_timestamp(last["created_at"]),
            )
        except Exception as exc:
            logger.error(
                "Episode generation failed: %s",
                type(exc).__name__,
            )

    def _complete(self, fan_id: str, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
            self._inflight.discard(fan_id)

    def wait_for_idle(self) -> None:
        with self._lock:
            futures = tuple(self._futures)
        if futures:
            wait(futures)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
