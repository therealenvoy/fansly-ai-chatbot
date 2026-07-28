from unittest.mock import MagicMock

import pytest

from src.webhooks.control import (
    WebhookControlError,
    WebhookControlService,
)
from src.webhooks.registry import (
    CORE_V1_DESIRED_EVENTS,
    EVENT_REGISTRY,
)


ENDPOINT = "https://bot.example/webhooks/onlyfansapi/fansly"


def _service(*, enabled=False):
    client = MagicMock()
    client.account_id = "account-a"
    client.list_fansly_webhooks.return_value = []
    repository = MagicMock()
    repository.webhook_metrics.return_value = {
        "delivery_count": 0,
        "provider_circuit": {"open": False},
    }
    service = WebhookControlService(
        client=client,
        repository=repository,
        creator_id="creator-a",
        endpoint_url=ENDPOINT,
        signing_secret="s" * 64,
        registration_enabled=enabled,
    )
    return service, client


def test_status_ignores_other_webhooks_and_exposes_no_secret():
    service, client = _service()
    client.list_fansly_webhooks.return_value = [
        {
            "id": "other",
            "url": "https://other.example/webhook",
            "enabled": True,
            "signing_secret": "must-not-leak",
        }
    ]

    status = service.status()

    assert status["registration"] is None
    assert status["registration_drift"] == [
        "owned_webhook_missing"
    ]
    assert "signing_secret" not in status
    assert len(status["handler_readiness"]) == 25


def test_reconcile_is_blocked_until_deployment_policy_enables_it():
    service, client = _service(enabled=False)

    with pytest.raises(
        WebhookControlError,
        match="disabled by deployment policy",
    ):
        service.reconcile()

    client.ensure_fansly_webhook.assert_not_called()


def test_reconcile_applies_exact_ready_core_profile():
    service, client = _service(enabled=True)
    client.ensure_fansly_webhook.return_value = {
        "id": "owned",
        "url": ENDPOINT,
        "enabled": True,
        "events": sorted(CORE_V1_DESIRED_EVENTS),
        "account_scope": "inclusive",
        "account_ids": ["account-a"],
        "has_signing_secret": True,
    }

    result = service.reconcile()

    assert result["applied"] is True
    args = client.ensure_fansly_webhook.call_args.args
    assert args[0] == ENDPOINT
    assert args[1] == ("s" * 64)
    assert set(args[2]) == CORE_V1_DESIRED_EVENTS


def test_health_check_reports_catalog_drift_without_mutation():
    service, client = _service()
    client.list_available_webhook_events.return_value = {
        "events": [
            {
                "value": spec.name,
                "description": spec.description,
            }
            for spec in EVENT_REGISTRY.values()
            if spec.name != "fansly.messages.read"
        ],
        "credits_used": 0,
    }

    result = service.health_check()

    assert result["healthy"] is False
    assert result["catalog_drift"]["missing"] == [
        "fansly.messages.read"
    ]
    client.ensure_fansly_webhook.assert_not_called()


def test_health_check_separates_fansly_and_provider_catalog_counts():
    service, client = _service()
    fansly_events = [
        {
            "value": spec.name,
            "description": spec.description,
        }
        for spec in EVENT_REGISTRY.values()
    ]
    client.list_available_webhook_events.return_value = {
        "events": [
            *fansly_events,
            {
                "value": "onlyfans.messages.received",
                "description": "An unrelated provider event",
            },
        ],
        "credits_used": 0,
    }

    result = service.health_check()

    assert result["catalog_event_count"] == len(EVENT_REGISTRY)
    assert result["provider_catalog_event_count"] == (
        len(EVENT_REGISTRY) + 1
    )
    assert result["catalog_drift"] == {
        "missing": [],
        "unexpected": [],
        "description_mismatches": [],
    }
    assert result["healthy"] is True
