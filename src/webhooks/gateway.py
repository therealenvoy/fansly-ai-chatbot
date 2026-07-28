"""Fail-closed validation for the universal OnlyFansAPI Fansly gateway."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from .onlyfansapi import (
    InvalidWebhookEvent,
    _mapping,
    _provider_datetime,
    _text,
    verify_onlyfansapi_signature,
)
from .registry import EVENT_REGISTRY, FanslyEventSpec


SUPPORTED_SIGNATURE_HEADERS = (
    "Signature",
    "X-Webhook-Signature",
)


class InvalidWebhookSignature(ValueError):
    """The request was not authenticated over its exact raw bytes."""


class WebhookAccountMismatch(ValueError):
    """The signed event targets a different provider account."""


class PermanentWebhookSchemaError(ValueError):
    """The signed payload cannot be processed without a contract change."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _normalized_signature(value: Any) -> str:
    result = str(value or "").strip().lower()
    if result.startswith("sha256="):
        result = result.split("=", 1)[1]
    return result


def supplied_signature(headers: Mapping[str, Any]) -> str | None:
    """Read supported signature headers and reject conflicting values."""
    observed = {
        normalized
        for name in SUPPORTED_SIGNATURE_HEADERS
        if (normalized := _normalized_signature(headers.get(name)))
    }
    if len(observed) > 1:
        raise InvalidWebhookSignature("conflicting signature headers")
    return next(iter(observed), None)


def _path_value(payload: Mapping[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _first_path_text(
    payload: Mapping[str, Any],
    paths: tuple[str, ...],
) -> str:
    return _text(*(_path_value(payload, path) for path in paths))


def _first_timestamp(
    payload: Mapping[str, Any],
    paths: tuple[str, ...],
) -> datetime | None:
    for path in paths:
        value = _path_value(payload, path)
        if value is None or value == "":
            continue
        try:
            return _provider_datetime(value)
        except InvalidWebhookEvent as exc:
            raise PermanentWebhookSchemaError(
                "invalid_provider_timestamp"
            ) from exc
    return None


@dataclass(frozen=True)
class OnlyFansApiWebhookEnvelope:
    event_name: str
    account_id: str
    event_key: str
    provider_event_id: str | None
    schema_version: str | None
    subject_id: str | None
    provider_created_at: datetime | None


@dataclass(frozen=True)
class ValidatedGatewayEvent:
    payload: dict
    envelope: OnlyFansApiWebhookEnvelope
    spec: FanslyEventSpec | None


def _envelope(
    payload: dict,
    *,
    expected_account_id: str,
) -> OnlyFansApiWebhookEnvelope:
    event_name = _text(payload.get("event"))
    if not event_name:
        raise PermanentWebhookSchemaError("missing_event_name")

    account_id = _text(
        payload.get("account_id"),
        payload.get("accountId"),
    )
    expected = _text(expected_account_id)
    if not account_id or account_id != expected:
        raise WebhookAccountMismatch("webhook account mismatch")

    provider_event_id = _text(
        payload.get("event_id"),
        payload.get("eventId"),
        payload.get("webhook_id"),
    )
    schema_version = _text(
        payload.get("version"),
        payload.get("schema_version"),
    )
    spec = EVENT_REGISTRY.get(event_name)
    subject_paths = (
        spec.subject_id_paths
        if spec is not None
        else (
            "payload.id",
            "payload.message.id",
            "data.id",
            "subject.id",
        )
    )
    timestamp_paths = (
        (
            "timestamp",
            "createdAt",
            "created_at",
        )
        + (
            spec.provider_timestamp_paths
            if spec is not None
            else (
                "payload.createdAt",
                "payload.created_at",
                "data.createdAt",
                "data.created_at",
            )
        )
    )
    subject_id = _first_path_text(payload, subject_paths)
    provider_created_at = _first_timestamp(payload, timestamp_paths)

    if provider_event_id:
        stable_material = "\0".join(
            (
                event_name,
                account_id,
                provider_event_id,
            )
        )
    else:
        if not subject_id:
            raise PermanentWebhookSchemaError("missing_subject_id")
        if provider_created_at is None:
            raise PermanentWebhookSchemaError(
                "missing_provider_timestamp"
            )
        stable_material = "\0".join(
            (
                event_name,
                account_id,
                subject_id,
                provider_created_at.astimezone(timezone.utc).isoformat(),
            )
        )
    event_key = hashlib.sha256(
        stable_material.encode("utf-8")
    ).hexdigest()
    return OnlyFansApiWebhookEnvelope(
        event_name=event_name,
        account_id=account_id,
        event_key=event_key,
        provider_event_id=provider_event_id or None,
        schema_version=schema_version or None,
        subject_id=subject_id or None,
        provider_created_at=provider_created_at,
    )


def validate_gateway_event(
    raw_body: bytes,
    headers: Mapping[str, Any],
    *,
    signing_secret: str,
    expected_account_id: str,
) -> ValidatedGatewayEvent:
    """Authenticate, decode, scope, and classify one webhook delivery."""
    signature = supplied_signature(headers)
    if not verify_onlyfansapi_signature(
        raw_body,
        signature,
        signing_secret,
    ):
        raise InvalidWebhookSignature("invalid signature")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermanentWebhookSchemaError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise PermanentWebhookSchemaError("invalid_payload_shape")

    envelope = _envelope(
        payload,
        expected_account_id=expected_account_id,
    )
    return ValidatedGatewayEvent(
        payload=payload,
        envelope=envelope,
        spec=EVENT_REGISTRY.get(envelope.event_name),
    )
