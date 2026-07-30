"""Validation and normalization for APIFansly webhook events.

The provider currently documents five active webhook event names. Only the
three events in ``APIFANSLY_SAFE_EVENT_PROFILE`` have complete, production
handlers in this application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any


APIFANSLY_CONTRACT_VERSION = "2026-07-08"
APIFANSLY_ACTIVE_EVENTS = (
    "messages.received",
    "messages.sent",
    "ppv.purchased",
    "subscriptions.new",
    "tips.received",
)
APIFANSLY_SAFE_EVENT_PROFILE = (
    "messages.received",
    "messages.sent",
    "ppv.purchased",
)
APIFANSLY_EVENT_FAMILIES = {
    "messages.received": "chat",
    "messages.sent": "chat",
    "ppv.purchased": "revenue",
    "subscriptions.new": "lifecycle",
    "tips.received": "revenue",
}


class InvalidApifanslyWebhookEvent(ValueError):
    """The authenticated APIFansly delivery cannot be safely projected."""


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""


def _provider_datetime(value: Any) -> datetime:
    if value is None or value == "":
        raise InvalidApifanslyWebhookEvent("missing provider timestamp")
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        try:
            result = datetime.fromtimestamp(numeric, timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise InvalidApifanslyWebhookEvent(
                "invalid provider timestamp"
            ) from error
    else:
        try:
            result = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        except ValueError as error:
            raise InvalidApifanslyWebhookEvent(
                "invalid provider timestamp"
            ) from error
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _validate_envelope(
    payload: dict,
    *,
    expected_event: str,
    expected_account_id: str,
) -> tuple[str, dict]:
    if not isinstance(payload, dict):
        raise InvalidApifanslyWebhookEvent("invalid webhook payload")
    event_name = _text(payload.get("event"))
    if event_name != expected_event:
        raise InvalidApifanslyWebhookEvent("unsupported event")
    account_id = _text(payload.get("accountId"))
    if not account_id or account_id != _text(expected_account_id):
        raise InvalidApifanslyWebhookEvent("webhook account mismatch")
    data = _mapping(payload.get("data"))
    if not data:
        raise InvalidApifanslyWebhookEvent("missing webhook data")
    return account_id, data


def _message_timestamp(payload: dict, data: dict) -> datetime:
    return _provider_datetime(
        data.get("createdAt")
        if data.get("createdAt") is not None
        else payload.get("timestamp")
    )


def _event_key(
    event_name: str,
    account_id: str,
    subject_id: str,
) -> str:
    return hashlib.sha256(
        "\0".join(
            (
                "apifansly",
                event_name,
                account_id,
                subject_id,
            )
        ).encode("utf-8")
    ).hexdigest()


def quarantine_event_key(payload: dict) -> str:
    """Return a deterministic privacy-safe key for an unsupported delivery."""
    event_name = _text(payload.get("event"), "unknown")
    account_id = _text(payload.get("accountId"), "unknown")
    data = _mapping(payload.get("data"))
    subject_id = _text(
        data.get("id"),
        data.get("orderId"),
        data.get("correlationId"),
        payload.get("timestamp"),
        "unknown",
    )
    return _event_key(event_name, account_id, subject_id)


@dataclass(frozen=True)
class ApifanslyReceivedMessage:
    platform_message_id: str
    account_id: str
    chat_id: str
    fan_id: str
    content: str
    provider_created_at: datetime
    attachments: tuple[dict, ...] = ()
    username: str | None = None
    display_name: str | None = None
    event_key: str = ""
    event_name: str = "messages.received"
    provider_event_id: str | None = None
    schema_version: str | None = APIFANSLY_CONTRACT_VERSION

    @classmethod
    def from_payload(
        cls,
        payload: dict,
        *,
        expected_account_id: str,
        creator_fansly_id: str | None = None,
    ) -> "ApifanslyReceivedMessage":
        account_id, data = _validate_envelope(
            payload,
            expected_event="messages.received",
            expected_account_id=expected_account_id,
        )
        platform_message_id = _text(data.get("id"))
        chat_id = _text(data.get("groupId"))
        fan_id = _text(data.get("senderId"))
        if not platform_message_id:
            raise InvalidApifanslyWebhookEvent("missing message ID")
        if not chat_id:
            raise InvalidApifanslyWebhookEvent("missing chat ID")
        if not fan_id:
            raise InvalidApifanslyWebhookEvent("missing fan ID")
        if creator_fansly_id and fan_id == str(creator_fansly_id):
            raise InvalidApifanslyWebhookEvent(
                "creator-authored received event"
            )
        attachments = tuple(
            item
            for item in (
                data.get("attachments")
                if isinstance(data.get("attachments"), list)
                else []
            )
            if isinstance(item, dict)
        )
        content = _text(data.get("content"))
        if not content and attachments:
            content = "[sent an attachment]"
        created_at = _message_timestamp(payload, data)
        return cls(
            event_key=_event_key(
                "messages.received",
                account_id,
                platform_message_id,
            ),
            provider_event_id=platform_message_id,
            platform_message_id=platform_message_id,
            account_id=account_id,
            chat_id=chat_id,
            fan_id=fan_id,
            content=content,
            provider_created_at=created_at,
            attachments=attachments,
        )


@dataclass(frozen=True)
class ApifanslySentMessage:
    platform_message_id: str
    account_id: str
    chat_id: str
    fan_id: str | None
    content: str
    provider_created_at: datetime
    attachments: tuple[dict, ...] = ()
    source_hint: str | None = None
    automation_id: str | None = None
    integration_id: str | None = None
    event_key: str = ""
    event_name: str = "messages.sent"
    provider_event_id: str | None = None
    schema_version: str | None = APIFANSLY_CONTRACT_VERSION

    @classmethod
    def from_payload(
        cls,
        payload: dict,
        *,
        expected_account_id: str,
        creator_fansly_id: str | None = None,
    ) -> "ApifanslySentMessage":
        account_id, data = _validate_envelope(
            payload,
            expected_event="messages.sent",
            expected_account_id=expected_account_id,
        )
        platform_message_id = _text(data.get("id"))
        chat_id = _text(data.get("groupId"))
        sender_id = _text(data.get("senderId"))
        if not platform_message_id:
            raise InvalidApifanslyWebhookEvent("missing message ID")
        if not chat_id:
            raise InvalidApifanslyWebhookEvent("missing chat ID")
        if (
            creator_fansly_id
            and sender_id
            and sender_id != str(creator_fansly_id)
        ):
            raise InvalidApifanslyWebhookEvent("fan-authored sent event")

        fan_id = _text(
            data.get("recipientId"),
            data.get("fanId"),
        )
        if not fan_id:
            interactions = data.get("interactions")
            if isinstance(interactions, list):
                for interaction in interactions:
                    if not isinstance(interaction, dict):
                        continue
                    candidate = _text(interaction.get("userId"))
                    if candidate and candidate != str(
                        creator_fansly_id or ""
                    ):
                        fan_id = candidate
                        break

        attachments = tuple(
            item
            for item in (
                data.get("attachments")
                if isinstance(data.get("attachments"), list)
                else []
            )
            if isinstance(item, dict)
        )
        created_at = _message_timestamp(payload, data)
        return cls(
            event_key=_event_key(
                "messages.sent",
                account_id,
                platform_message_id,
            ),
            provider_event_id=platform_message_id,
            platform_message_id=platform_message_id,
            account_id=account_id,
            chat_id=chat_id,
            fan_id=fan_id or None,
            content=_text(data.get("content")),
            provider_created_at=created_at,
            attachments=attachments,
            source_hint=_text(
                data.get("source"),
                payload.get("source"),
            )
            or None,
            automation_id=_text(data.get("automationId")) or None,
            integration_id=_text(data.get("integrationId")) or None,
        )
