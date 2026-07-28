import json
from pathlib import Path

import pytest

from src.webhooks.registry import (
    CATALOG_VERSION,
    CORE_V1_DESIRED_EVENTS,
    CORE_V1_PROFILE,
    EVENT_REGISTRY,
    HandlerReadiness,
    compare_live_catalog,
    eligible_event_names,
    profile_blockers,
)


CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "config"
    / "webhooks"
    / "fansly-events-2026-07-28.json"
)


def _contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_live_contract_fixture_matches_the_registry():
    contract = _contract()

    assert contract["catalog_version"] == CATALOG_VERSION
    assert contract["credits_used_to_verify"] == 0
    assert len(contract["events"]) == 25
    assert {event["value"] for event in contract["events"]} == set(
        EVENT_REGISTRY
    )
    assert compare_live_catalog(contract["events"]).has_drift is False


def test_every_event_declares_complete_operational_metadata():
    assert len(EVENT_REGISTRY) == 25
    for name, spec in EVENT_REGISTRY.items():
        assert name.startswith("fansly.")
        assert spec.name == name
        assert spec.description
        assert spec.family
        assert spec.handler_name
        assert spec.parser_version
        assert spec.persistence_targets
        assert spec.subject_id_paths
        assert spec.provider_timestamp_paths
        assert spec.retention
        if spec.intentionally_ignored:
            assert spec.readiness is HandlerReadiness.IGNORED
            assert spec.subscription_eligible is False


def test_core_profile_is_14_events_but_only_ready_handlers_are_eligible():
    assert len(CORE_V1_DESIRED_EVENTS) == 14
    assert eligible_event_names(CORE_V1_PROFILE) == (
        "fansly.messages.received",
    )
    assert set(profile_blockers(CORE_V1_PROFILE)) == (
        CORE_V1_DESIRED_EVENTS - {"fansly.messages.received"}
    )


def test_unknown_profile_fails_closed():
    with pytest.raises(ValueError, match="unknown webhook event profile"):
        eligible_event_names("future_profile")


def test_contract_drift_reports_unknown_missing_and_description_changes():
    live = list(_contract()["events"])
    live = [
        event
        for event in live
        if event["value"] != "fansly.messages.read"
    ]
    live.append(
        {
            "value": "fansly.future.event",
            "description": "Future event",
        }
    )
    live[0] = {
        **live[0],
        "description": "Changed provider description",
    }

    drift = compare_live_catalog(live)

    assert drift.has_drift is True
    assert drift.missing == ("fansly.messages.read",)
    assert drift.unexpected == ("fansly.future.event",)
    assert drift.description_mismatches == (
        "fansly.messages.received",
    )
