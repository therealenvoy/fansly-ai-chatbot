"""Privacy-safe production logging configuration.

Exception messages can contain SQL parameters, provider response bodies, or
other fan data. Keep traceback locations for diagnosis while omitting the
exception message itself.
"""

from __future__ import annotations

import logging
import traceback
from types import TracebackType


DEFAULT_LOG_FORMAT = (
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


class PrivacySafeFormatter(logging.Formatter):
    """Render traceback frames and the exception type without its message."""

    def formatException(
        self,
        exc_info: tuple[type[BaseException], BaseException, TracebackType | None],
    ) -> str:
        exception_type, _exception, traceback_value = exc_info
        frames = (
            traceback.format_list(traceback.extract_tb(traceback_value))
            if traceback_value is not None
            else []
        )
        return "".join(frames) + exception_type.__name__


def configure_privacy_safe_logging(
    *,
    level: int = logging.INFO,
) -> None:
    """Install the safe formatter on every active root handler."""

    root_logger = logging.getLogger()
    formatter = PrivacySafeFormatter(DEFAULT_LOG_FORMAT)
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
    root_logger.setLevel(level)
