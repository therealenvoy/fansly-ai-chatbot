"""Contract tests for the documented APIFansly webhook payloads."""

import json
from pathlib import Path

import pytest

from src.webhooks.apifansly import (
    APIFANSLY_ACTIVE_EVENTS,
    APIFANSLY_SAFE_EVENT_PROFILE,
    ApifanslyReceivedMessage,
    ApifanslySentMessage,
    InvalidApifanslyWebhookEvent,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "apifansly"
ACCOUNT_ID = "fansly_ACCOUNT_TEST"
CREATOR_ID = "CREATOR_TEST"


def _fixture(name: str) -> dict:
    return json.loads(
        (FIXTURES / name).read_text(encoding="utf-8")
    )


def test_active_and_safe_event_contract_is_explicit():
    assert APIFANSLY_ACTIVE_EVENTS == (
        "messages.received",
        "messages.sent",
        "ppv.purchased",
        "subscriptions.new",
        "tips.received",
    )
    assert APIFANSLY_SAFE_EVENT_PROFILE == (
        "messages.received",
        "messages.sent",
        "ppv.purchased",
    )


def test_received_message_fixture_normalizes_to_durable_work():
    event = ApifanslyReceivedMessage.from_payload(
        _fixture("messages_received.json"),
        expected_account_id=ACCOUNT_ID,
        creator_fansly_id=CREATOR_ID,
    )

    assert event.platform_message_id == "MESSAGE_TEST"
    assert event.chat_id == "GROUP_TEST"
    assert event.fan_id == "FAN_TEST"
    assert event.event_name == "messages.received"
    assert len(event.event_key) == 64


def test_sent_message_fan_is_resolved_from_interactions():
    event = ApifanslySentMessage.from_payload(
        _fixture("messages_sent.json"),
        expected_account_id=ACCOUNT_ID,
        creator_fansly_id=CREATOR_ID,
    )

    assert event.platform_message_id == "MESSAGE_SENT_TEST"
    assert event.chat_id == "GROUP_TEST"
    assert event.fan_id == "FAN_TEST"
    assert event.event_name == "messages.sent"


def test_wrong_connected_account_is_rejected_before_projection():
    with pytest.raises(
        InvalidApifanslyWebhookEvent,
        match="account mismatch",
    ):
        ApifanslyReceivedMessage.from_payload(
            _fixture("messages_received.json"),
            expected_account_id="different-account",
            creator_fansly_id=CREATOR_ID,
        )


def test_received_creator_authored_message_is_rejected():
    payload = _fixture("messages_received.json")
    payload["data"]["senderId"] = CREATOR_ID

    with pytest.raises(
        InvalidApifanslyWebhookEvent,
        match="creator-authored",
    ):
        ApifanslyReceivedMessage.from_payload(
            payload,
            expected_account_id=ACCOUNT_ID,
            creator_fansly_id=CREATOR_ID,
        )
