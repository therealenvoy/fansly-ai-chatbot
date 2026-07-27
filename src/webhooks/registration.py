"""Safe automatic registration for OnlyFansAPI Fansly webhooks."""

import hashlib
import hmac
from typing import Mapping

_DERIVATION_CONTEXT = b"onlyfansapi-fansly-webhook-v1"
_WEBHOOK_PATH = "/webhooks/onlyfansapi/fansly"
_MIN_SECRET_LENGTH = 32


def resolve_signing_secret(env: Mapping[str, str]) -> str:
    """Return an explicit secret or derive an isolated one from an existing key."""
    explicit = str(env.get("ONLYFANSAPI_WEBHOOK_SECRET", "")).strip()
    if explicit:
        if len(explicit) < _MIN_SECRET_LENGTH:
            raise ValueError(
                "ONLYFANSAPI_WEBHOOK_SECRET must be at least 32 characters"
            )
        return explicit

    seed = (
        str(env.get("CREDENTIAL_ENCRYPTION_KEY", "")).strip()
        or str(env.get("APIFANSLY_WEBHOOK_TOKEN", "")).strip()
    )
    if not seed:
        return ""
    if len(seed) < _MIN_SECRET_LENGTH:
        raise ValueError(
            "Webhook secret derivation source must be at least 32 characters"
        )
    return hmac.new(seed.encode(), _DERIVATION_CONTEXT, hashlib.sha256).hexdigest()


def production_webhook_url(env: Mapping[str, str]) -> str:
    """Build the public HTTPS endpoint Railway exposes for this service."""
    domain = str(env.get("RAILWAY_PUBLIC_DOMAIN", "")).strip().strip("/")
    if not domain:
        return ""
    if "://" in domain or "/" in domain:
        raise ValueError("RAILWAY_PUBLIC_DOMAIN must be a hostname")
    return f"https://{domain}{_WEBHOOK_PATH}"
