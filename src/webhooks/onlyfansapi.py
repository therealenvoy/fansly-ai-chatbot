"""Validation and normalization for OnlyFansAPI Fansly webhooks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
from typing import Any


FANSLY_MESSAGE_EVENTS = frozenset(
    {
        "fansly.messages.received",
    }
)


class InvalidWebhookEvent(ValueError):
    """The signed request is not a usable inbound Fansly message."""


def verify_onlyfansapi_signature(
    raw_body: bytes,
    supplied_signature: str | None,
    signing_secret: str,
) -> bool:
    """Verify the provider's hex HMAC-SHA256 ``Signature`` header."""
    secret = str(signing_secret or "").strip()
    supplied = str(supplied_signature or "").strip()
    if len(secret) < 32 or not supplied:
        return False
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    if len(supplied) != 64:
        return False
    try:
        int(supplied, 16)
    except ValueError:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(
        supplied.lower().encode("ascii"),
        expected.encode("ascii"),
    )


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
        raise InvalidWebhookEvent("missing provider timestamp")
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000
        result = datetime.fromtimestamp(numeric, timezone.utc)
    else:
        try:
            result = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise InvalidWebhookEvent(
                "invalid provider timestamp"
            ) from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class OnlyFansApiFanslyMessage:
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
    event_name: str = "fansly.messages.received"
    provider_event_id: str | None = None
    schema_version: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict,
        *,
        expected_account_id: str,
        creator_fansly_id: str | None = None,
    ) -> "OnlyFansApiFanslyMessage":
        if not isinstance(payload, dict):
            raise InvalidWebhookEvent("invalid webhook payload")

        event_name = _text(payload.get("event"))
        if event_name not in FANSLY_MESSAGE_EVENTS:
            raise InvalidWebhookEvent("unsupported event")
        provider_event_id = _text(
            payload.get("event_id"),
            payload.get("eventId"),
            payload.get("webhook_id"),
        )
        schema_version = _text(
            payload.get("version"),
            payload.get("schema_version"),
        )

        account_id = _text(
            payload.get("account_id"),
            payload.get("accountId"),
        )
        expected = _text(expected_account_id)
        if not account_id or account_id != expected:
            raise InvalidWebhookEvent("webhook account mismatch")

        envelope = _mapping(payload.get("payload")) or _mapping(
            payload.get("data")
        )
        message = _mapping(envelope.get("message")) or envelope
        sender = (
            _mapping(message.get("sender"))
            or _mapping(message.get("fromUser"))
            or _mapping(envelope.get("fan"))
        )

        platform_message_id = _text(
            message.get("id"),
            message.get("messageId"),
            message.get("message_id"),
        )
        if not platform_message_id:
            raise InvalidWebhookEvent("missing message ID")

        chat_id = _text(
            message.get("groupId"),
            message.get("chatId"),
            message.get("chat_id"),
            envelope.get("groupId"),
            envelope.get("chatId"),
            envelope.get("chat_id"),
        )
        if not chat_id:
            raise InvalidWebhookEvent("missing chat ID")

        fan_id = _text(
            message.get("senderId"),
            message.get("sender_id"),
            envelope.get("senderId"),
            envelope.get("fanId"),
            envelope.get("fan_id"),
            sender.get("id"),
        )
        if not fan_id:
            raise InvalidWebhookEvent("missing fan ID")
        if creator_fansly_id and fan_id == str(creator_fansly_id):
            raise InvalidWebhookEvent("creator-authored message")

        attachments_raw = message.get("attachments")
        attachments = tuple(
            item
            for item in (
                attachments_raw if isinstance(attachments_raw, list) else []
            )
            if isinstance(item, dict)
        )
        content = _text(
            message.get("content"),
            message.get("text"),
        )
        if not content and attachments:
            content = "[sent an attachment]"

        created_at = _provider_datetime(
            message.get("createdAt")
            if message.get("createdAt") is not None
            else message.get("created_at")
        )
        username = _text(
            sender.get("username"),
            envelope.get("username"),
        )
        display_name = _text(
            sender.get("displayName"),
            sender.get("display_name"),
            sender.get("name"),
            envelope.get("displayName"),
        )
        stable_material = "\0".join(
            (
                event_name,
                account_id,
                platform_message_id,
            )
        )
        event_key = hashlib.sha256(
            stable_material.encode("utf-8")
        ).hexdigest()
        return cls(
            event_key=event_key,
            event_name=event_name,
            provider_event_id=provider_event_id or None,
            schema_version=schema_version or None,
            platform_message_id=platform_message_id,
            account_id=account_id,
            chat_id=chat_id,
            fan_id=fan_id,
            content=content,
            provider_created_at=created_at,
            attachments=attachments,
            username=username or None,
            display_name=display_name or None,
        )


def _event_message(payload: dict, expected_event: str) -> tuple[
    str,
    str,
    str | None,
    str | None,
    dict,
    dict,
]:
    if not isinstance(payload, dict):
        raise InvalidWebhookEvent("invalid webhook payload")
    event_name = _text(payload.get("event"))
    if event_name != expected_event:
        raise InvalidWebhookEvent("unsupported event")
    account_id = _text(
        payload.get("account_id"),
        payload.get("accountId"),
    )
    provider_event_id = _text(
        payload.get("event_id"),
        payload.get("eventId"),
        payload.get("webhook_id"),
    )
    schema_version = _text(
        payload.get("version"),
        payload.get("schema_version"),
    )
    envelope = _mapping(payload.get("payload")) or _mapping(
        payload.get("data")
    )
    message = _mapping(envelope.get("message")) or envelope
    return (
        event_name,
        account_id,
        provider_event_id or None,
        schema_version or None,
        envelope,
        message,
    )


def _validate_account(account_id: str, expected_account_id: str) -> None:
    expected = _text(expected_account_id)
    if not account_id or account_id != expected:
        raise InvalidWebhookEvent("webhook account mismatch")


def _message_id(message: dict, envelope: dict) -> str:
    result = _text(
        message.get("id"),
        message.get("messageId"),
        message.get("message_id"),
        envelope.get("messageId"),
        envelope.get("message_id"),
    )
    if not result:
        raise InvalidWebhookEvent("missing message ID")
    return result


def _chat_id(message: dict, envelope: dict) -> str:
    result = _text(
        message.get("groupId"),
        message.get("chatId"),
        message.get("chat_id"),
        envelope.get("groupId"),
        envelope.get("chatId"),
        envelope.get("chat_id"),
    )
    if not result:
        raise InvalidWebhookEvent("missing chat ID")
    return result


def _message_timestamp(
    payload: dict,
    message: dict,
    envelope: dict,
) -> datetime:
    return _provider_datetime(
        message.get("createdAt")
        if message.get("createdAt") is not None
        else (
            message.get("created_at")
            if message.get("created_at") is not None
            else (
                envelope.get("createdAt")
                if envelope.get("createdAt") is not None
                else (
                    envelope.get("created_at")
                    if envelope.get("created_at") is not None
                    else payload.get("timestamp")
                )
            )
        )
    )


def _stable_event_key(
    event_name: str,
    account_id: str,
    subject_id: str,
    provider_created_at: datetime,
    provider_event_id: str | None,
) -> str:
    material = (
        (event_name, account_id, provider_event_id)
        if provider_event_id
        else (
            event_name,
            account_id,
            subject_id,
            provider_created_at.astimezone(timezone.utc).isoformat(),
        )
    )
    return hashlib.sha256(
        "\0".join(material).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class OnlyFansApiFanslySentMessage:
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
    event_name: str = "fansly.messages.sent"
    provider_event_id: str | None = None
    schema_version: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict,
        *,
        expected_account_id: str,
        creator_fansly_id: str | None = None,
    ) -> "OnlyFansApiFanslySentMessage":
        (
            event_name,
            account_id,
            provider_event_id,
            schema_version,
            envelope,
            message,
        ) = _event_message(payload, "fansly.messages.sent")
        _validate_account(account_id, expected_account_id)
        platform_message_id = _message_id(message, envelope)
        chat_id = _chat_id(message, envelope)
        sender_id = _text(
            message.get("senderId"),
            message.get("sender_id"),
            envelope.get("senderId"),
        )
        if (
            creator_fansly_id
            and sender_id
            and sender_id != str(creator_fansly_id)
        ):
            raise InvalidWebhookEvent("fan-authored sent event")
        recipient = (
            _mapping(message.get("recipient"))
            or _mapping(envelope.get("fan"))
            or _mapping(envelope.get("recipient"))
        )
        fan_id = _text(
            message.get("recipientId"),
            message.get("recipient_id"),
            message.get("fanId"),
            envelope.get("recipientId"),
            envelope.get("fanId"),
            envelope.get("fan_id"),
            recipient.get("id"),
        )
        attachments = tuple(
            item
            for item in (
                message.get("attachments")
                if isinstance(message.get("attachments"), list)
                else []
            )
            if isinstance(item, dict)
        )
        content = _text(
            message.get("content"),
            message.get("text"),
        )
        created_at = _message_timestamp(
            payload,
            message,
            envelope,
        )
        source_hint = _text(
            message.get("source"),
            envelope.get("source"),
            payload.get("source"),
        )
        automation_id = _text(
            message.get("automationId"),
            message.get("automation_id"),
            envelope.get("automationId"),
            envelope.get("automation_id"),
        )
        integration_id = _text(
            message.get("integrationId"),
            message.get("integration_id"),
            envelope.get("integrationId"),
            envelope.get("integration_id"),
        )
        return cls(
            event_key=_stable_event_key(
                event_name,
                account_id,
                platform_message_id,
                created_at,
                provider_event_id,
            ),
            event_name=event_name,
            provider_event_id=provider_event_id,
            schema_version=schema_version,
            platform_message_id=platform_message_id,
            account_id=account_id,
            chat_id=chat_id,
            fan_id=fan_id or None,
            content=content,
            provider_created_at=created_at,
            attachments=attachments,
            source_hint=source_hint or None,
            automation_id=automation_id or None,
            integration_id=integration_id or None,
        )


@dataclass(frozen=True)
class OnlyFansApiFanslyDeletedMessage:
    platform_message_id: str
    account_id: str
    chat_id: str | None
    fan_id: str | None
    provider_created_at: datetime
    event_key: str = ""
    event_name: str = "fansly.messages.deleted"
    provider_event_id: str | None = None
    schema_version: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict,
        *,
        expected_account_id: str,
    ) -> "OnlyFansApiFanslyDeletedMessage":
        (
            event_name,
            account_id,
            provider_event_id,
            schema_version,
            envelope,
            message,
        ) = _event_message(payload, "fansly.messages.deleted")
        _validate_account(account_id, expected_account_id)
        platform_message_id = _message_id(message, envelope)
        chat_id = _text(
            message.get("groupId"),
            message.get("chatId"),
            envelope.get("groupId"),
            envelope.get("chatId"),
        )
        fan_id = _text(
            message.get("senderId"),
            message.get("recipientId"),
            envelope.get("fanId"),
            envelope.get("fan_id"),
        )
        created_at = _message_timestamp(
            payload,
            message,
            envelope,
        )
        return cls(
            event_key=_stable_event_key(
                event_name,
                account_id,
                platform_message_id,
                created_at,
                provider_event_id,
            ),
            event_name=event_name,
            provider_event_id=provider_event_id,
            schema_version=schema_version,
            platform_message_id=platform_message_id,
            account_id=account_id,
            chat_id=chat_id or None,
            fan_id=fan_id or None,
            provider_created_at=created_at,
        )


@dataclass(frozen=True)
class OnlyFansApiFanslyReadReceipt:
    platform_message_ids: tuple[str, ...]
    account_id: str
    chat_id: str | None
    fan_id: str | None
    provider_created_at: datetime
    event_key: str = ""
    event_name: str = "fansly.messages.read"
    provider_event_id: str | None = None
    schema_version: str | None = None

    @classmethod
    def from_payload(
        cls,
        payload: dict,
        *,
        expected_account_id: str,
    ) -> "OnlyFansApiFanslyReadReceipt":
        (
            event_name,
            account_id,
            provider_event_id,
            schema_version,
            envelope,
            message,
        ) = _event_message(payload, "fansly.messages.read")
        _validate_account(account_id, expected_account_id)
        raw_ids = (
            envelope.get("messageIds")
            or envelope.get("message_ids")
            or message.get("messageIds")
            or message.get("message_ids")
        )
        message_ids: list[str] = []
        if isinstance(raw_ids, list):
            for item in raw_ids:
                value = (
                    _text(item.get("id"))
                    if isinstance(item, dict)
                    else _text(item)
                )
                if value:
                    message_ids.append(value)
        if not message_ids:
            message_ids.append(_message_id(message, envelope))
        message_ids = list(dict.fromkeys(message_ids))
        chat_id = _text(
            message.get("groupId"),
            message.get("chatId"),
            envelope.get("groupId"),
            envelope.get("chatId"),
        )
        fan_id = _text(
            envelope.get("fanId"),
            envelope.get("fan_id"),
            envelope.get("userId"),
            message.get("recipientId"),
        )
        created_at = _message_timestamp(
            payload,
            message,
            envelope,
        )
        subject_id = ",".join(sorted(message_ids))
        return cls(
            event_key=_stable_event_key(
                event_name,
                account_id,
                subject_id,
                created_at,
                provider_event_id,
            ),
            event_name=event_name,
            provider_event_id=provider_event_id,
            schema_version=schema_version,
            platform_message_ids=tuple(message_ids),
            account_id=account_id,
            chat_id=chat_id or None,
            fan_id=fan_id or None,
            provider_created_at=created_at,
        )
