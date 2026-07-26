"""Small, secret-free runtime telemetry for operational checks."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class RuntimeMonitor:
    """Track polling health without depending on an external metrics system."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = _now()
        self._last_poll_started_at: datetime | None = None
        self._last_poll_succeeded_at: datetime | None = None
        self._last_activity_at: datetime | None = None
        self._last_error_at: datetime | None = None
        self._last_error: str | None = None
        self._consecutive_failures = 0
        self._consecutive_idle_cycles = 0

    def poll_started(self) -> None:
        with self._lock:
            self._last_poll_started_at = _now()

    def poll_succeeded(self, *, had_activity: bool) -> None:
        with self._lock:
            now = _now()
            self._last_poll_succeeded_at = now
            self._consecutive_failures = 0
            if had_activity:
                self._last_activity_at = now
                self._consecutive_idle_cycles = 0
            else:
                self._consecutive_idle_cycles += 1

    def poll_failed(self, error: BaseException | str) -> None:
        with self._lock:
            self._last_error_at = _now()
            self._last_error = (
                type(error).__name__
                if isinstance(error, BaseException)
                else "RuntimeError"
            )
            self._consecutive_failures += 1
            self._consecutive_idle_cycles = 0

    def provider_blocked(self, error: BaseException | str) -> None:
        """Record an auth/billing block without treating it as a retry storm."""
        with self._lock:
            self._last_error_at = _now()
            self._last_error = (
                type(error).__name__
                if isinstance(error, BaseException)
                else "ProviderBlocked"
            )
            self._consecutive_failures = 0
            self._consecutive_idle_cycles = 0

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "started_at": _iso(self._started_at),
                "last_poll_started_at": _iso(self._last_poll_started_at),
                "last_poll_succeeded_at": _iso(
                    self._last_poll_succeeded_at
                ),
                "last_activity_at": _iso(self._last_activity_at),
                "last_error_at": _iso(self._last_error_at),
                "last_error": self._last_error,
                "consecutive_failures": self._consecutive_failures,
                "consecutive_idle_cycles": self._consecutive_idle_cycles,
            }
