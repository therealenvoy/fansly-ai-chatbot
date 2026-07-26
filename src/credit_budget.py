"""Conservative API credit estimates for polling configuration."""

from __future__ import annotations


BASIC_MONTHLY_CREDITS = 20_000
CONTROLLED_LAUNCH_MIN_POLL_INTERVAL = 300
BASELINE_CALLS_PER_POLL = 2
THIRTY_DAY_MONTH_SECONDS = 30 * 24 * 60 * 60


def estimate_minimum_monthly_requests(
    poll_interval_seconds: int,
    *,
    calls_per_poll: int = BASELINE_CALLS_PER_POLL,
) -> int:
    """Estimate the minimum 30-day request count before sends or pagination.

    Each enabled poll performs a wallet transaction sync and a chat-list fetch.
    The estimate deliberately excludes message retrieval, pagination, and sends.
    """
    if poll_interval_seconds <= 0:
        raise ValueError("poll interval must be positive")
    if calls_per_poll <= 0:
        raise ValueError("calls per poll must be positive")
    polls = (
        THIRTY_DAY_MONTH_SECONDS + poll_interval_seconds - 1
    ) // poll_interval_seconds
    return polls * calls_per_poll
