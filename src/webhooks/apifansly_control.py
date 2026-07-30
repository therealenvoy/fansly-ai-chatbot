"""Secret-free operator status for the APIFansly webhook receiver."""

from __future__ import annotations

from dataclasses import dataclass

from .apifansly import (
    APIFANSLY_ACTIVE_EVENTS,
    APIFANSLY_SAFE_EVENT_PROFILE,
)


class ApifanslyWebhookControlError(RuntimeError):
    """A safe operator-facing APIFansly webhook control failure."""


@dataclass(frozen=True)
class ApifanslyWebhookControlService:
    repository: object | None
    creator_id: str
    receiver_enabled: bool
    receiver_token_configured: bool
    recovery_polling_enabled: bool

    def _metrics(self) -> dict:
        if self.repository is None:
            return {}
        return self.repository.webhook_metrics(
            creator_id=self.creator_id
        )

    def status(self) -> dict:
        readiness = {
            "messages.received": True,
            "messages.sent": True,
            "ppv.purchased": True,
            "subscriptions.new": False,
            "tips.received": False,
        }
        return {
            "provider": "apifansly",
            "provider_console_url": "https://app.apifansly.com/webhooks",
            "registration_management": "provider_console",
            "registration_enabled": self.receiver_enabled,
            "receiver_authentication": "secret_route_token",
            "receiver_secret_configured": self.receiver_token_configured,
            "endpoint_url": "/webhooks/apifansly/[redacted]",
            "event_profile": "apifansly_core_v1",
            "desired_events": list(APIFANSLY_SAFE_EVENT_PROFILE),
            "active_provider_events": list(APIFANSLY_ACTIVE_EVENTS),
            "handler_readiness": [
                {
                    "event_name": event_name,
                    "handler_ready": readiness[event_name],
                    "subscription_eligible": (
                        event_name in APIFANSLY_SAFE_EVENT_PROFILE
                    ),
                }
                for event_name in APIFANSLY_ACTIVE_EVENTS
            ],
            "recovery_polling_enabled": self.recovery_polling_enabled,
            "metrics": self._metrics(),
        }

    def reconcile(self) -> dict:
        raise ApifanslyWebhookControlError(
            "APIFansly webhook registration is managed in the provider console"
        )

    def pause(self) -> dict:
        raise ApifanslyWebhookControlError(
            "APIFansly webhook registration is managed in the provider console"
        )

    def health_check(self) -> dict:
        configured = (
            self.receiver_enabled
            and self.receiver_token_configured
            and not self.recovery_polling_enabled
        )
        return {
            "provider": "apifansly",
            "receiver_configured": configured,
            "desired_events": list(APIFANSLY_SAFE_EVENT_PROFILE),
            "polling_disabled": not self.recovery_polling_enabled,
            "provider_registration_verification": "manual_console",
            "healthy": configured,
        }
