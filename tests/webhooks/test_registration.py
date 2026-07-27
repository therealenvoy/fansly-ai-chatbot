import hashlib
import hmac

import pytest

from src.webhooks.registration import production_webhook_url, resolve_signing_secret


def test_explicit_webhook_secret_wins():
    assert resolve_signing_secret({
        "ONLYFANSAPI_WEBHOOK_SECRET": "e" * 64,
        "CREDENTIAL_ENCRYPTION_KEY": "c" * 64,
    }) == ("e" * 64)


def test_secret_is_deterministically_derived_from_existing_key():
    seed = "c" * 64
    expected = hmac.new(seed.encode(), b"onlyfansapi-fansly-webhook-v1", hashlib.sha256).hexdigest()
    assert resolve_signing_secret({"CREDENTIAL_ENCRYPTION_KEY": seed}) == expected


def test_webhook_token_is_secondary_derivation_source():
    assert len(resolve_signing_secret({"APIFANSLY_WEBHOOK_TOKEN": "t" * 64})) == 64


def test_missing_secret_source_disables_registration():
    assert resolve_signing_secret({}) == ""


def test_short_explicit_secret_fails_closed():
    with pytest.raises(ValueError, match="at least 32"):
        resolve_signing_secret({
            "ONLYFANSAPI_WEBHOOK_SECRET": "short",
            "CREDENTIAL_ENCRYPTION_KEY": "c" * 64,
        })


def test_railway_public_domain_builds_https_endpoint():
    assert production_webhook_url({"RAILWAY_PUBLIC_DOMAIN": "sunny.example"}) == (
        "https://sunny.example/webhooks/onlyfansapi/fansly"
    )


def test_missing_public_domain_disables_registration():
    assert production_webhook_url({}) == ""
