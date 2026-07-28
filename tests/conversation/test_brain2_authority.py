from dataclasses import replace

from src.conversation.authority import BrainAuthorityRouter
from src.conversation.brain2 import BrainRuntimeSettings


def _advanced_settings(percent):
    return BrainRuntimeSettings(
        mode="advanced",
        allow_advanced_send=True,
        live_percent=percent,
        max_live_percent=100,
    )


def test_current_and_shadow_modes_never_grant_advanced_authority():
    router = BrainAuthorityRouter()
    for mode in ("current", "shadow"):
        result = router.select(
            settings=BrainRuntimeSettings(
                mode=mode,
                allow_advanced_send=True,
                live_percent=100,
                max_live_percent=100,
            ),
            creator_id="creator-a",
            fan_id="fan-a",
        )
        assert result.authority == "current"
        assert result.reason == f"mode_{mode}"


def test_advanced_zero_percent_and_deployment_guard_stay_current():
    router = BrainAuthorityRouter()
    zero = router.select(
        settings=_advanced_settings(0),
        creator_id="creator-a",
        fan_id="fan-a",
    )
    blocked = router.select(
        settings=replace(_advanced_settings(100), allow_advanced_send=False),
        creator_id="creator-a",
        fan_id="fan-a",
    )
    assert zero.authority == "current"
    assert zero.reason == "live_percent_zero"
    assert blocked.authority == "current"
    assert blocked.reason == "deployment_guard_blocked"


def test_requested_percentage_cannot_exceed_deployment_ceiling():
    result = BrainAuthorityRouter().select(
        settings=replace(_advanced_settings(10), max_live_percent=5),
        creator_id="creator-a",
        fan_id="fan-a",
    )
    assert result.authority == "current"
    assert result.reason == "deployment_ceiling_exceeded"


def test_assignment_is_sticky_per_creator_fan_version_and_experiment():
    router = BrainAuthorityRouter()
    settings = _advanced_settings(10)
    first = router.select(
        settings=settings,
        creator_id="creator-a",
        fan_id="fan-17",
        experiment_id="exp-a",
    )
    again = router.select(
        settings=settings,
        creator_id="creator-a",
        fan_id="fan-17",
        experiment_id="exp-a",
    )
    assert first == again


def test_assignment_percentages_are_bounded_and_100_percent_selects_all():
    router = BrainAuthorityRouter()
    for percent in (1, 5, 10):
        advanced = sum(
            router.select(
                settings=_advanced_settings(percent),
                creator_id="creator-a",
                fan_id=f"fan-{index}",
            ).authority
            == "advanced"
            for index in range(10_000)
        )
        assert abs(advanced - percent * 100) < 120
    assert all(
        router.select(
            settings=_advanced_settings(100),
            creator_id="creator-a",
            fan_id=f"fan-{index}",
        ).authority
        == "advanced"
        for index in range(100)
    )
