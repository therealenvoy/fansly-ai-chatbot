import pytest

from src.credit_budget import estimate_minimum_monthly_requests


def test_estimates_two_baseline_calls_per_poll_at_sixty_seconds():
    assert estimate_minimum_monthly_requests(60) == 86_400


def test_five_minute_interval_fits_basic_monthly_baseline():
    assert estimate_minimum_monthly_requests(300) == 17_280


@pytest.mark.parametrize("interval", [0, -1])
def test_rejects_nonpositive_poll_interval(interval):
    with pytest.raises(ValueError, match="positive"):
        estimate_minimum_monthly_requests(interval)
