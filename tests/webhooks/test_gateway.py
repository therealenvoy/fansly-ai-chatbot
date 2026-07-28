import hashlib
import hmac
import json

import pytest

from src.webhooks.gateway import (
    InvalidWebhookSignature,
    PermanentWebhookSchemaError,
    WebhookAccountMismatch,
    validate_gateway_event,
)


SECRET = "webhook-signing-secret-with-enough-entropy"


def _payload(event="fansly.messages.received"):
    return {
        "event": event,
        "account_id": "fansly_acct_test",
        "payload": {
            "id": "subject-1",
            "createdAt": "2026-07-28T00:00:00Z",
        },
    }


def _delivery(payload, *, headers=None):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(
        SECRET.encode(),
        raw,
        hashlib.sha256,
    ).hexdigest()
    return raw, headers or {"Signature": signature}


def test_signature_is_checked_before_json_parsing():
    with pytest.raises(InvalidWebhookSignature):
        validate_gateway_event(
            b"{not-json",
            {"Signature": "0" * 64},
            signing_secret=SECRET,
            expected_account_id="fansly_acct_test",
        )


def test_conflicting_supported_signature_headers_are_rejected():
    raw, _ = _delivery(_payload())

    with pytest.raises(
        InvalidWebhookSignature,
        match="conflicting",
    ):
        validate_gateway_event(
            raw,
            {
                "Signature": "1" * 64,
                "X-Webhook-Signature": "2" * 64,
            },
            signing_secret=SECRET,
            expected_account_id="fansly_acct_test",
        )


def test_equivalent_signature_headers_are_accepted():
    raw, headers = _delivery(_payload())
    headers["X-Webhook-Signature"] = (
        f"sha256={headers['Signature']}"
    )

    event = validate_gateway_event(
        raw,
        headers,
        signing_secret=SECRET,
        expected_account_id="fansly_acct_test",
    )

    assert event.envelope.event_name == "fansly.messages.received"
    assert event.spec is not None
    assert event.spec.handler_ready is True


def test_account_is_validated_before_event_lookup():
    payload = _payload("fansly.future.event")
    payload["account_id"] = "wrong-account"
    raw, headers = _delivery(payload)

    with pytest.raises(WebhookAccountMismatch):
        validate_gateway_event(
            raw,
            headers,
            signing_secret=SECRET,
            expected_account_id="fansly_acct_test",
        )


def test_unknown_signed_event_is_classified_without_raw_storage():
    raw, headers = _delivery(_payload("fansly.future.event"))

    first = validate_gateway_event(
        raw,
        headers,
        signing_secret=SECRET,
        expected_account_id="fansly_acct_test",
    )
    second = validate_gateway_event(
        raw,
        headers,
        signing_secret=SECRET,
        expected_account_id="fansly_acct_test",
    )

    assert first.spec is None
    assert first.envelope.subject_id == "subject-1"
    assert first.envelope.event_key == second.envelope.event_key
    assert len(first.envelope.event_key) == 64


def test_missing_idempotency_material_is_permanent_schema_drift():
    payload = _payload()
    payload["payload"] = {}
    raw, headers = _delivery(payload)

    with pytest.raises(
        PermanentWebhookSchemaError,
        match="missing_subject_id",
    ):
        validate_gateway_event(
            raw,
            headers,
            signing_secret=SECRET,
            expected_account_id="fansly_acct_test",
        )
