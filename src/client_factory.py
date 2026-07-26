"""Build the configured provider adapter used by the application."""

from .fansly_client import FanslyApiClient
from .apifansly_client import ApifanslyClient, ApifanslyConfig
from .fansly_api_client import FanslyApiClientImpl


def get_fansly_client(env: dict) -> FanslyApiClient:
    """Build the configured Fansly API client from an env-var mapping.

    APIFansly uses APIFANSLY_API_KEY plus FANSLY_ACCOUNT_ID. The existing
    OnlyFansAPI beta adapter uses FANSLY_API_KEY.
    """
    provider = env.get("FANSLY_PROVIDER", "apifansly").strip().lower()

    if provider == "apifansly":
        return ApifanslyClient(
            ApifanslyConfig(
                api_key=env.get(
                    "APIFANSLY_API_KEY",
                    env.get("FANSLY_API_KEY", ""),
                ),
                account_id=env.get("FANSLY_ACCOUNT_ID", ""),
                webhook_token=env.get(
                    "APIFANSLY_WEBHOOK_TOKEN",
                    "",
                ),
            )
        )

    if provider == "fanslyapi":
        return FanslyApiClientImpl(
            api_key=env.get("FANSLY_API_KEY", "")
        )

    raise ValueError(
        f"Unsupported FANSLY_PROVIDER: '{provider}'. "
        "Expected 'apifansly' or 'fanslyapi'."
    )
