"""Tests for the provider client factory."""

import pytest

from src.client_factory import get_fansly_client
from src.apifansly_client import ApifanslyClient


def test_defaults_to_apifansly_for_paid_ppv():
    client = get_fansly_client({
        "APIFANSLY_API_KEY": "api_test",
        "FANSLY_ACCOUNT_ID": "fansly_acc_test",
        "APIFANSLY_WEBHOOK_TOKEN": "w" * 32,
    })

    assert isinstance(client, ApifanslyClient)
    assert client.config.api_key == "api_test"
    assert client.account_id == "fansly_acc_test"
    assert client.config.webhook_token == "w" * 32


def test_rejects_the_removed_legacy_provider():
    with pytest.raises(ValueError, match="Only 'apifansly' is supported"):
        get_fansly_client(
            {
                "FANSLY_PROVIDER": "fanslyapi",
                "FANSLY_API_KEY": "legacy-key",
            }
        )


def test_returns_apifansly_when_explicitly_set():
    env = {
        "FANSLY_PROVIDER": "apifansly",
        "APIFANSLY_API_KEY": "api-key",
        "FANSLY_ACCOUNT_ID": "connected-account",
        "APIFANSLY_WEBHOOK_TOKEN": "x" * 32,
    }

    client = get_fansly_client(env)

    assert isinstance(client, ApifanslyClient)
    assert client.config.api_key == "api-key"
    assert client.account_id == "connected-account"
    assert client.config.webhook_token == "x" * 32


def test_raises_on_unknown_provider():
    env = {
        "FANSLY_PROVIDER": "not_a_real_provider",
        "APIFANSLY_API_KEY": "k",
    }

    with pytest.raises(ValueError, match="Unsupported FANSLY_PROVIDER"):
        get_fansly_client(env)


def test_does_not_fall_back_to_the_legacy_api_key_name():
    client = get_fansly_client(
        {
            "FANSLY_PROVIDER": "apifansly",
            "FANSLY_API_KEY": "must-not-be-used",
            "FANSLY_ACCOUNT_ID": "connected-account",
        }
    )

    assert client.config.api_key == ""
