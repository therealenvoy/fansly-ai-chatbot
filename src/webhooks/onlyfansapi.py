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
        # The provider's generic event catalogue currently documents the
        # unprefixed name while webhook configuration documents fansly.*.
        # Account scoping still makes this form unambiguously Fansly.
        "messages.received",
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
        return datetime.now(timezone.utc)
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
        return cls(
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
