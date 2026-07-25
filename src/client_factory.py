"""Selects the concrete Fansly API client from FANSLY_PROVIDER."""

from .fansly_client import FanslyApiClient, ApifanslyClient, FanslyConfig
from .fansly_api_client import FanslyApiClientImpl


def get_fansly_client(env: dict) -> FanslyApiClient:
    """Build the configured Fansly API client from an env-var mapping.

    env: a dict-like object (typically os.environ) with FANSLY_PROVIDER,
    FANSLY_API_KEY, and (for apifansly) FANSLY_ACCOUNT_ID.
    """
    provider = env.get("FANSLY_PROVIDER", "apifansly")
    api_key = env.get("FANSLY_API_KEY", "")

    if provider == "apifansly":
        account_id = env.get("FANSLY_ACCOUNT_ID", "")
        if not account_id:
            raise ValueError("FANSLY_ACCOUNT_ID is required for FANSLY_PROVIDER=apifansly")
        return ApifanslyClient(FanslyConfig(api_key=api_key, account_id=account_id))

    if provider == "fanslyapi":
        return FanslyApiClientImpl(api_key=api_key)

    raise ValueError(f"Unknown FANSLY_PROVIDER: '{provider}' (expected 'apifansly' or 'fanslyapi')")
