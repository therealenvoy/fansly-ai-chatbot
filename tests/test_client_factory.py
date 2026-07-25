"""Tests for the Fansly API provider factory."""
import pytest

from src.fansly_client import ApifanslyClient
from src.fansly_api_client import FanslyApiClientImpl
from src.client_factory import get_fansly_client


def test_defaults_to_apifansly_when_unset():
    client = get_fansly_client({"FANSLY_API_KEY": "k", "FANSLY_ACCOUNT_ID": "a"})
    assert isinstance(client, ApifanslyClient)


def test_returns_apifansly_when_explicitly_set():
    env = {"FANSLY_PROVIDER": "apifansly", "FANSLY_API_KEY": "k", "FANSLY_ACCOUNT_ID": "a"}
    client = get_fansly_client(env)
    assert isinstance(client, ApifanslyClient)
    assert client.config.api_key == "k"
    assert client.config.account_id == "a"


def test_returns_fanslyapi_when_set():
    env = {"FANSLY_PROVIDER": "fanslyapi", "FANSLY_API_KEY": "sk_test"}
    client = get_fansly_client(env)
    assert isinstance(client, FanslyApiClientImpl)
    assert client.api_key == "sk_test"


def test_raises_on_unknown_provider():
    env = {"FANSLY_PROVIDER": "not_a_real_provider", "FANSLY_API_KEY": "k"}
    with pytest.raises(ValueError, match="Unknown FANSLY_PROVIDER"):
        get_fansly_client(env)


def test_raises_when_apifansly_missing_account_id():
    env = {"FANSLY_PROVIDER": "apifansly", "FANSLY_API_KEY": "k"}
    with pytest.raises(ValueError, match="FANSLY_ACCOUNT_ID"):
        get_fansly_client(env)
