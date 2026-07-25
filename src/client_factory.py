"""Builds the OnlyFansAPI Fansly client used by the application."""

from .fansly_client import FanslyApiClient
from .fansly_api_client import FanslyApiClientImpl


def get_fansly_client(env: dict) -> FanslyApiClient:
    """Build the configured Fansly API client from an env-var mapping.

    env: a dict-like object (typically os.environ) with FANSLY_PROVIDER and
    FANSLY_API_KEY.
    """
    provider = env.get("FANSLY_PROVIDER", "fanslyapi")
    api_key = env.get("FANSLY_API_KEY", "")

    if provider == "fanslyapi":
        return FanslyApiClientImpl(api_key=api_key)

    raise ValueError(
        f"Unsupported FANSLY_PROVIDER: '{provider}'. "
        "This application only supports OnlyFansAPI's Fansly product ('fanslyapi')."
    )
