"""Build the configured provider adapter used by the application."""

from .fansly_client import FanslyApiClient
from .apifansly_client import ApifanslyClient, ApifanslyConfig


def get_fansly_client(env: dict) -> FanslyApiClient:
    """Build the configured Fansly API client from an env-var mapping.

    APIFansly uses APIFANSLY_API_KEY plus FANSLY_ACCOUNT_ID. No alternate
    provider or legacy API-key fallback is accepted.
    """
    provider = env.get("FANSLY_PROVIDER", "apifansly").strip().lower()

    if provider != "apifansly":
        raise ValueError(
            f"Unsupported FANSLY_PROVIDER: '{provider}'. "
            "Only 'apifansly' is supported."
        )

    return ApifanslyClient(
        ApifanslyConfig(
            api_key=env.get("APIFANSLY_API_KEY", ""),
            account_id=env.get("FANSLY_ACCOUNT_ID", ""),
            webhook_token=env.get(
                "APIFANSLY_WEBHOOK_TOKEN",
                "",
            ),
        )
    )
