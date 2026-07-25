"""Tests for the OnlyFansAPI Fansly client factory."""

import pytest

from src.client_factory import get_fansly_client
from src.fansly_api_client import FanslyApiClientImpl


def test_defaults_to_onlyfansapi_fansly_when_unset():
    client = get_fansly_client({"FANSLY_API_KEY": "sk_test"})

    assert isinstance(client, FanslyApiClientImpl)
    assert client.api_key == "sk_test"


def test_returns_onlyfansapi_fansly_when_explicitly_set():
    client = get_fansly_client(
        {"FANSLY_PROVIDER": "fanslyapi", "FANSLY_API_KEY": "sk_test"}
    )

    assert isinstance(client, FanslyApiClientImpl)
    assert client.api_key == "sk_test"


def test_legacy_apifansly_provider_is_rejected():
    env = {
        "FANSLY_PROVIDER": "apifansly",
        "APIFANSLY_API_KEY": "legacy-key",
        "FANSLY_ACCOUNT_ID": "legacy-account",
    }

    with pytest.raises(ValueError, match="only supports OnlyFansAPI"):
        get_fansly_client(env)


def test_raises_on_unknown_provider():
    env = {"FANSLY_PROVIDER": "not_a_real_provider", "FANSLY_API_KEY": "k"}

    with pytest.raises(ValueError, match="Unsupported FANSLY_PROVIDER"):
        get_fansly_client(env)
