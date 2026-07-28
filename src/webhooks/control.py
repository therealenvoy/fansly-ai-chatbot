"""Authenticated, secret-free control plane for the owned Fansly webhook."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from .registry import (
    CORE_V1_PROFILE,
    EVENT_REGISTRY,
    compare_live_catalog,
    eligible_event_names,
    profile_blockers,
)


class WebhookControlError(RuntimeError):
    """A safe operator-facing webhook control failure."""


class WebhookControlService:
    """Inspect and reconcile only the application's exact webhook endpoint."""

    def __init__(
        self,
        *,
        client,
        repository,
        creator_id: str,
        endpoint_url: str,
        signing_secret: str,
        registration_enabled: bool,
        event_profile: str = CORE_V1_PROFILE,
        credit_snapshot: Callable[[], dict] | None = None,
    ):
        self.client = client
        self.repository = repository
        self.creator_id = creator_id
        self.endpoint_url = endpoint_url.strip()
        self.signing_secret = signing_secret.strip()
        self.registration_enabled = bool(registration_enabled)
        self.event_profile = event_profile.strip() or CORE_V1_PROFILE
        self.credit_snapshot = credit_snapshot

    @property
    def desired_events(self) -> tuple[str, ...]:
        try:
            return eligible_event_names(self.event_profile)
        except ValueError as error:
            raise WebhookControlError(str(error)) from error

    def _metrics(self) -> dict:
        if self.repository is None:
            return {}
        return self.repository.webhook_metrics(
            creator_id=self.creator_id
        )

    def _list_provider_webhooks(self) -> list[dict]:
        method = getattr(self.client, "list_fansly_webhooks", None)
        if not callable(method):
            raise WebhookControlError(
                "Fansly webhook controls are unavailable for this provider"
            )
        return method()

    def _owned_rows(self, rows: list[dict]) -> list[dict]:
        return [
            row
            for row in rows
            if str(
                row.get("url") or row.get("endpoint_url") or ""
            ).strip()
            == self.endpoint_url
        ]

    @staticmethod
    def _safe_registration(row: dict | None) -> dict | None:
        if row is None:
            return None
        return {
            "id": str(row.get("id") or ""),
            "enabled": bool(row.get("enabled")),
            "endpoint_url": str(
                row.get("url") or row.get("endpoint_url") or ""
            ),
            "events": sorted(
                str(event_name)
                for event_name in (row.get("events") or [])
            ),
            "account_scope": str(row.get("account_scope") or ""),
            "account_ids": sorted(
                str(account_id)
                for account_id in (row.get("account_ids") or [])
            ),
            "has_signing_secret": bool(
                row.get("has_signing_secret")
            ),
        }

    def _account_id(self) -> str:
        try:
            return str(getattr(self.client, "account_id", "") or "")
        except Exception as error:
            raise WebhookControlError(
                "The connected Fansly account could not be resolved"
            ) from error

    def status(self) -> dict:
        desired = self.desired_events
        blockers = profile_blockers(self.event_profile)
        provider_error = None
        rows: list[dict] = []
        try:
            rows = self._list_provider_webhooks()
        except Exception as error:
            provider_error = type(error).__name__
        owned = self._owned_rows(rows)
        registration = (
            self._safe_registration(owned[0])
            if len(owned) == 1
            else None
        )
        drift: list[str] = []
        if not self.endpoint_url:
            drift.append("endpoint_not_configured")
        elif len(owned) == 0:
            drift.append("owned_webhook_missing")
        elif len(owned) > 1:
            drift.append("multiple_owned_webhooks")
        elif registration is not None:
            if not registration["has_signing_secret"]:
                drift.append("signing_secret_missing")
            if not registration["enabled"]:
                drift.append("disabled")
            if set(registration["events"]) != set(desired):
                drift.append("event_set_mismatch")
            if registration["account_scope"] != "inclusive":
                drift.append("account_scope_mismatch")
            expected_account_id = self._account_id()
            if (
                expected_account_id
                and set(registration["account_ids"])
                != {expected_account_id}
            ):
                drift.append("account_ids_mismatch")
        if provider_error:
            drift.append("provider_status_unavailable")

        return {
            "registration_enabled": self.registration_enabled,
            "event_profile": self.event_profile,
            "endpoint_url": self.endpoint_url,
            "receiver_secret_configured": (
                len(self.signing_secret) >= 32
            ),
            "registration": registration,
            "registration_drift": sorted(set(drift)),
            "provider_error": provider_error,
            "desired_events": list(desired),
            "profile_blockers": list(blockers),
            "handler_readiness": [
                {
                    **asdict(spec),
                    "readiness": spec.readiness.value,
                    "retention": spec.retention.value,
                    "handler_ready": spec.handler_ready,
                }
                for spec in EVENT_REGISTRY.values()
            ],
            "metrics": self._metrics(),
            "provider_credit": (
                self.credit_snapshot()
                if self.credit_snapshot is not None
                else {}
            ),
        }

    def reconcile(self) -> dict:
        if not self.registration_enabled:
            raise WebhookControlError(
                "Webhook registration is disabled by deployment policy"
            )
        if not self.endpoint_url.startswith("https://"):
            raise WebhookControlError(
                "The production HTTPS webhook endpoint is not configured"
            )
        if len(self.signing_secret) < 32:
            raise WebhookControlError(
                "A strong receiver signing secret is not configured"
            )
        if profile_blockers(self.event_profile):
            raise WebhookControlError(
                "The desired event profile contains unready handlers"
            )
        metrics = self._metrics()
        if metrics.get("provider_circuit", {}).get("open"):
            raise WebhookControlError(
                "The provider safety circuit is open"
            )
        method = getattr(self.client, "ensure_fansly_webhook", None)
        if not callable(method):
            raise WebhookControlError(
                "Fansly webhook reconciliation is unavailable"
            )
        result = method(
            self.endpoint_url,
            self.signing_secret,
            self.desired_events,
        )
        return {
            "applied": True,
            "registration": self._safe_registration(result),
        }

    def pause(self) -> dict:
        if not self.endpoint_url.startswith("https://"):
            raise WebhookControlError(
                "The production HTTPS webhook endpoint is not configured"
            )
        method = getattr(self.client, "pause_fansly_webhook", None)
        if not callable(method):
            raise WebhookControlError(
                "Fansly webhook pause is unavailable"
            )
        result = method(self.endpoint_url)
        return {
            "paused": True,
            "registration": self._safe_registration(result),
        }

    def health_check(self) -> dict:
        method = getattr(
            self.client,
            "list_available_webhook_events",
            None,
        )
        if not callable(method):
            raise WebhookControlError(
                "Live Fansly event catalog inspection is unavailable"
            )
        catalog = method()
        drift = compare_live_catalog(catalog.get("events") or [])
        credits_used = catalog.get("credits_used")
        if credits_used not in (0, None):
            raise WebhookControlError(
                "The provider reported non-zero catalog inspection credits"
            )
        metrics = self._metrics()
        return {
            "catalog_event_count": len(catalog.get("events") or []),
            "catalog_credits_used": credits_used,
            "catalog_drift": {
                "missing": list(drift.missing),
                "unexpected": list(drift.unexpected),
                "description_mismatches": list(
                    drift.description_mismatches
                ),
            },
            "receiver_configured": (
                bool(self.endpoint_url)
                and len(self.signing_secret) >= 32
            ),
            "signed_delivery_observed": (
                int(metrics.get("delivery_count", 0)) > 0
            ),
            "healthy": (
                not drift.has_drift
                and len(self.signing_secret) >= 32
                and not profile_blockers(self.event_profile)
            ),
        }
