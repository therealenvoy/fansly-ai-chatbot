import hashlib
import hmac
import json
from datetime import timezone

import pytest

from src.webhooks.onlyfansapi import (
    InvalidWebhookEvent,
    OnlyFansApiFanslyMessage,
    verify_onlyfansapi_signature,
)


SECRET = "webhook-signing-secret-with-enough-entropy"


def _payload():
    return {
        "event": "fansly.messages.received",
        "account_id": "fansly_acct_test",
        "payload": {
            "id": "message-1",
            "groupId": "chat-1",
            "senderId": "fan-1",
            "content": "hey babe",
            "createdAt": 1_722_000_000.25,
            "attachments": [],
            "sender": {
                "username": "fan_username",
                "displayName": "Fan Name",
            },
        },
    }


def test_signature_verification_uses_raw_body_hmac_sha256():
    raw = json.dumps(_payload(), separators=(",", ":")).encode()
    signature = hmac.new(
        SECRET.encode(),
        raw,
        hashlib.sha256,
    ).hexdigest()

    assert verify_onlyfansapi_signature(raw, signature, SECRET) is True
    assert (
        verify_onlyfansapi_signature(
            raw,
            f"sha256={signature}",
            SECRET,
        )
        is True
    )
    assert verify_onlyfansapi_signature(raw + b" ", signature, SECRET) is False


def test_fansly_message_event_normalizes_provider_fields():
    event = OnlyFansApiFanslyMessage.from_payload(
        _payload(),
        expected_account_id="fansly_acct_test",
        creator_fansly_id="creator-1",
    )

    assert event.platform_message_id == "message-1"
    assert event.chat_id == "chat-1"
    assert event.fan_id == "fan-1"
    assert event.content == "hey babe"
    assert event.username == "fan_username"
    assert event.display_name == "Fan Name"
    assert event.provider_created_at.tzinfo == timezone.utc


def test_message_event_accepts_nested_message_and_attachment_only_content():
    payload = _payload()
    payload["payload"] = {
        "message": {
            "messageId": "message-2",
            "chatId": "chat-2",
            "senderId": "fan-2",
            "text": "",
            "created_at": "2026-07-28T00:00:00Z",
            "attachments": [{"id": "media-1"}],
        }
    }

    event = OnlyFansApiFanslyMessage.from_payload(
        payload,
        expected_account_id="fansly_acct_test",
        creator_fansly_id="creator-1",
    )

    assert event.content == "[sent an attachment]"
    assert event.attachments == ({"id": "media-1"},)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda payload: payload.update(
                {"account_id": "fansly_acct_other"}
            ),
            "account mismatch",
        ),
        (
            lambda payload: payload["payload"].update(
                {"senderId": "creator-1"}
            ),
            "creator-authored",
        ),
        (
            lambda payload: payload.update({"event": "users.online"}),
            "unsupported event",
        ),
        (
            lambda payload: payload["payload"].pop("groupId"),
            "chat ID",
        ),
    ],
)
def test_invalid_or_wrong_scope_events_fail_closed(mutate, match):
    payload = _payload()
    mutate(payload)

    with pytest.raises(InvalidWebhookEvent, match=match):
        OnlyFansApiFanslyMessage.from_payload(
            payload,
            expected_account_id="fansly_acct_test",
            creator_fansly_id="creator-1",
        )
