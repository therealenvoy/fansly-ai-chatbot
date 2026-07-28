"""Best-effort Memory V2 extraction outside the reply-critical path."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
import logging
import threading


logger = logging.getLogger(__name__)


class MemoryExtractionService:
    def __init__(
        self,
        *,
        fact_extractor,
        memory_writer,
        note_repository,
        note_extractor,
        max_workers: int = 1,
    ):
        self.fact_extractor = fact_extractor
        self.memory_writer = memory_writer
        self.note_repository = note_repository
        self.note_extractor = note_extractor
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 2)),
            thread_name_prefix="brain-memory",
        )
        self._futures: set[Future] = set()
        self._inflight: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        creator_id: str,
        fan_id: str,
        fan_texts: list[str],
        source_message_id: str,
        source_timestamp,
    ) -> bool:
        key = (creator_id, fan_id)
        with self._lock:
            if key in self._inflight:
                return False
            self._inflight.add(key)
        future = self._executor.submit(
            self._process,
            key,
            list(fan_texts),
            str(source_message_id),
            source_timestamp,
        )
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(
            lambda completed, target=key: self._complete(target, completed)
        )
        return True

    def _process(
        self,
        key: tuple[str, str],
        fan_texts: list[str],
        source_message_id: str,
        source_timestamp,
    ) -> None:
        creator_id, fan_id = key
        try:
            extracted = self.fact_extractor.extract(fan_texts)
            if not extracted:
                return
            self.memory_writer.write(
                creator_id=creator_id,
                fan_id=fan_id,
                extracted=extracted,
                source_message_id=source_message_id,
                source_timestamp=source_timestamp,
            )
            note = self.note_repository.get(fan_id, creator_id)
            if note is not None:
                self.note_repository.save(
                    self.note_extractor.merge(note, extracted)
                )
            logger.info(
                "Memory extraction completed with %s fields",
                len(extracted),
            )
        except Exception as exc:
            logger.error(
                "Asynchronous memory extraction failed: %s",
                type(exc).__name__,
            )

    def _complete(
        self,
        key: tuple[str, str],
        future: Future,
    ) -> None:
        with self._lock:
            self._futures.discard(future)
            self._inflight.discard(key)

    def wait_for_idle(self) -> None:
        with self._lock:
            futures = tuple(self._futures)
        if futures:
            wait(futures)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)
