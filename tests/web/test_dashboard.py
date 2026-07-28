"""Tests for the dashboard's bot on/off switch — /health, /api/bot/status,
/api/bot/toggle. This is the only control surface for enabling/disabling the
live bot, so it's tested against a real HTTPServer and a real (temp-file)
SettingsStore rather than mocked end-to-end, to catch real persistence bugs.
"""
import json
import base64
import hashlib
import hmac
import re
import threading
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from unittest.mock import MagicMock

import pytest

from src.fansly_client import ProviderCapabilities
from src.bot import LaunchGuardError
from src.notes.repository import FAN_NOTES_TABLE
from src.memory.store import MessageStore
from src.persistence.crm import CrmSyncRepository
from src.settings.chat_guidance import ChatGuidanceService
from src.settings.store import SettingsStore
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository
from src.sequences.models import (
    Sequence,
    SequenceStep,
    SequenceTrigger,
)
from src.sequences.repository import SequenceRepository
from src.web.dashboard import DASHBOARD_HTML, MAX_BODY_BYTES, DashboardServer
from src.webhooks.repository import WebhookIngestResult
from src.webhooks.registry import EVENT_REGISTRY


TEST_USER = "test-operator"
TEST_PASSWORD = "correct-horse-battery-staple"
TEST_CSRF_TOKEN = "test-csrf-token-with-enough-entropy"
TEST_WEBHOOK_TOKEN = "test-webhook-token-with-enough-entropy"
TEST_ONLYFANSAPI_WEBHOOK_SECRET = (
    "test-onlyfansapi-webhook-secret-with-enough-entropy"
)


def _authorization(user=TEST_USER, password=TEST_PASSWORD):
    credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {credentials}"


class TestDashboardShell:
    """Regression checks for the responsive dashboard navigation."""

    def test_all_primary_destinations_are_semantic_buttons(self):
        for tab in (
            "dashboard",
            "funnel",
            "vault",
            "fans",
            "scripts",
            "kpis",
            "sequences",
            "settings",
        ):
            assert f'class="nav-item' in DASHBOARD_HTML
            assert f'data-tab="{tab}"' in DASHBOARD_HTML
        assert '<nav aria-label="Primary">' in DASHBOARD_HTML

    def test_mobile_navigation_is_not_hidden(self):
        assert "@media(max-width:720px)" in DASHBOARD_HTML
        assert ".sidebar nav{display:grid" in DASHBOARD_HTML
        assert "aside{display:none}" not in DASHBOARD_HTML

    def test_bot_status_is_global_and_accessible(self):
        assert 'id="bot-toggle"' in DASHBOARD_HTML
        assert 'aria-label="Toggle bot"' in DASHBOARD_HTML
        assert "button.setAttribute('aria-pressed'" in DASHBOARD_HTML

    def test_start_stop_control_is_visible_inside_inbox_and_settings(self):
        assert DASHBOARD_HTML.count('data-bot-control') >= 2
        assert DASHBOARD_HTML.count("botControlMarkup()") >= 3
        assert 'data-off-label="Start bot"' in DASHBOARD_HTML
        assert 'data-on-label="Stop bot"' in DASHBOARD_HTML
        assert 'data-bot-reason' in DASHBOARD_HTML
        assert "document.querySelectorAll('[data-bot-control]')" in DASHBOARD_HTML

    def test_inline_event_handlers_are_not_used(self):
        assert " onclick=" not in DASHBOARD_HTML
        assert " onchange=" not in DASHBOARD_HTML

    def test_reference_led_dark_visual_system_is_present(self):
        assert "color-scheme:dark" in DASHBOARD_HTML
        assert 'class="app-shell"' in DASHBOARD_HTML
        assert 'class="hero-card surface"' in DASHBOARD_HTML
        assert 'class="aurora"' in DASHBOARD_HTML
        assert "Creator Intelligence" in DASHBOARD_HTML

    def test_dashboard_and_messages_use_existing_read_contracts(self):
        for endpoint in (
            "/api/kpis",
            "/api/conversations",
            "/api/bot/status",
            "/api/operations",
        ):
            assert endpoint in DASHBOARD_HTML
        assert 'id="conversation-search"' in DASHBOARD_HTML
        assert "function selectConversation(fanId)" in DASHBOARD_HTML
        assert "load-older-messages" in DASHBOARD_HTML
        assert "history_complete" in DASHBOARD_HTML
        assert "load-more-conversations" in DASHBOARD_HTML
        assert "Loading latest messages from Fansly" in DASHBOARD_HTML

    def test_inbox_conversation_list_owns_its_vertical_scroll(self):
        assert (
            ".conversation-rail{display:flex;flex-direction:column;"
            "min-height:0;overflow:hidden;"
        ) in DASHBOARD_HTML
        assert (
            ".conversation-list{flex:1;min-height:0;overflow-y:auto;"
        ) in DASHBOARD_HTML

    def test_inbox_distinguishes_local_preview_from_live_sync(self):
        assert "conversationLiveSyncAvailable" in DASHBOARD_HTML
        assert "Stored preview" in DASHBOARD_HTML
        assert "Live sync is not connected" in DASHBOARD_HTML

    def test_content_editors_and_media_picker_are_present(self):
        assert "Script Studio" in DASHBOARD_HTML
        assert 'id="script-messages"' in DASHBOARD_HTML
        assert "/api/scripts" in DASHBOARD_HTML
        assert "conditions:dashboardScriptDraft.conditions||{}" in DASHBOARD_HTML
        assert "variables:dashboardScriptDraft.variables" in DASHBOARD_HTML
        assert "/api/media-assets" in DASHBOARD_HTML
        assert "/api/vault-albums" in DASHBOARD_HTML
        assert 'id="media-provider-id"' in DASHBOARD_HTML
        assert 'id="persona-tone"' in DASHBOARD_HTML
        assert 'id="persona-boundaries"' in DASHBOARD_HTML
        assert 'id="deepseek-key" type="password"' in DASHBOARD_HTML
        assert 'autocomplete="new-password"' in DASHBOARD_HTML
        assert "/api/ai/settings" in DASHBOARD_HTML
        assert "/api/ai/connection/test" in DASHBOARD_HTML
        assert 'id="chat-instructions"' in DASHBOARD_HTML
        assert 'maxlength="50000"' in DASHBOARD_HTML
        assert "/api/chat-instructions" in DASHBOARD_HTML
        assert "stored in the database" in DASHBOARD_HTML
        assert "Voice Lab" in DASHBOARD_HTML
        assert "/api/human-delivery/status" in DASHBOARD_HTML
        assert "/api/human-delivery/documents" in DASHBOARD_HTML
        assert "/api/human-delivery/preview" in DASHBOARD_HTML
        assert "zero provider calls and zero sends" in DASHBOARD_HTML
        assert "function pickMedia(idx)" in DASHBOARD_HTML


def _request(host, method, path, body="", headers=None):
    conn = HTTPConnection(host, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    response_body = resp.read()
    response_headers = {name.lower(): value for name, value in resp.getheaders()}
    conn.close()
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        parsed = response_body.decode("utf-8")
    return resp.status, parsed, response_headers


def _get(host, path, *, authenticated=True, headers=None):
    request_headers = dict(headers or {})
    if authenticated:
        request_headers["Authorization"] = _authorization()
    status, body, _ = _request(host, "GET", path, headers=request_headers)
    return status, body


def _post(host, path, payload=None, *, authenticated=True, csrf=True, origin=None):
    body = json.dumps(payload) if payload is not None else ""
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = _authorization()
    if csrf:
        headers["X-CSRF-Token"] = TEST_CSRF_TOKEN
    headers["Origin"] = origin or f"http://{host}"
    status, data, _ = _request(host, "POST", path, body=body, headers=headers)
    return status, data


def _post_text(host, path, value, *, content_type="text/plain; charset=utf-8"):
    headers = {
        "Authorization": _authorization(),
        "X-CSRF-Token": TEST_CSRF_TOKEN,
        "Origin": f"http://{host}",
        "Content-Type": content_type,
    }
    status, data, _ = _request(
        host,
        "POST",
        path,
        body=value,
        headers=headers,
    )
    return status, data


def _post_webhook(host, token, payload):
    status, data, _ = _request(
        host,
        "POST",
        f"/webhooks/apifansly/{token}",
        body=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    return status, data


def _post_onlyfansapi_webhook(
    host,
    payload,
    *,
    secret=TEST_ONLYFANSAPI_WEBHOOK_SECRET,
):
    raw = json.dumps(payload, separators=(",", ":"))
    signature = hmac.new(
        secret.encode(),
        raw.encode(),
        hashlib.sha256,
    ).hexdigest()
    status, data, _ = _request(
        host,
        "POST",
        "/webhooks/onlyfansapi/fansly",
        body=raw,
        headers={
            "Content-Type": "application/json",
            "Signature": signature,
        },
    )
    return status, data


def _delete(host, path, *, authenticated=True, csrf=True, origin=None):
    headers = {}
    if authenticated:
        headers["Authorization"] = _authorization()
    if csrf:
        headers["X-CSRF-Token"] = TEST_CSRF_TOKEN
    headers["Origin"] = origin or f"http://{host}"
    status, data, _ = _request(host, "DELETE", path, headers=headers)
    return status, data


def _make_bot(db_url):
    """A MagicMock bot with real toggle() semantics and a real DB url for
    _bot_toggle's SettingsStore(db_url=...) reconstruction to use."""
    bot = MagicMock()
    bot.enabled = True
    bot.creator_id = "test_creator"
    bot.account_id = "account-123"
    bot.client.account_id = "fansly_acc_test"
    bot.client._creator_fansly_id = "creator-native-1"
    bot.client.creator_fansly_id = "creator-native-1"
    bot.client.list_chats.return_value = []
    bot.client.list_fansly_webhooks.return_value = []
    bot.client.list_available_webhook_events.return_value = {
        "events": [],
        "credits_used": 0,
    }
    bot.client.verify_auth.return_value = True
    bot.client.capabilities = ProviderCapabilities(
        supports_free_media_messages=True,
        supports_paid_messages=True,
        supports_attributed_purchases=True,
        supports_wallet_transactions=True,
        supports_vault_albums=True,
    )
    engine = create_database_engine(
        db_url,
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    FAN_NOTES_TABLE.create(engine, checkfirst=True)
    bot.note_repo.engine = engine
    bot.message_store = MessageStore(engine=engine)
    bot.state_repo = ConversationStateRepository(engine)
    bot.state_repo.ensure_creator(bot.creator_id)
    bot.sessions = {}
    bot.sequence_repo = SequenceRepository(engine=engine)
    bot.sequence_repo.create_tables()
    bot.record_provider_ppv_purchase.return_value = (
        MagicMock(),
        True,
    )
    bot.ingest_webhook_message.return_value = True
    bot.ingest_webhook_sent.return_value = WebhookIngestResult(
        True,
        None,
    )
    bot.ingest_webhook_deleted.return_value = WebhookIngestResult(
        True,
        None,
    )
    bot.ingest_webhook_read.return_value = WebhookIngestResult(
        True,
        None,
    )
    bot.ingest_webhook_account.return_value = WebhookIngestResult(
        True,
        None,
    )
    bot.ingest_webhook_domain.return_value = WebhookIngestResult(
        True,
        None,
    )
    bot.webhook_event_repo.webhook_metrics.return_value = {
        "delivery_count": 0,
        "duplicate_count": 0,
        "quarantined_count": 0,
        "provider_circuit": {"open": False},
    }
    bot.ai_settings = MagicMock()
    bot.ai_settings.status.return_value = {
        "provider": "DeepSeek",
        "configured": True,
        "model": "deepseek-v4-flash",
        "source": "encrypted_crm",
        "secure_storage_available": True,
        "supported_models": [
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ],
        "last_test_ok": True,
        "last_checked_at": "2026-07-27T00:00:00+00:00",
        "error": None,
    }
    bot.ai_settings.save.return_value = bot.ai_settings.status.return_value
    bot.ai_settings.test_connection.return_value = (
        bot.ai_settings.status.return_value
    )

    def _toggle(force=None):
        bot.enabled = bool(force) if force is not None else not bot.enabled
        return bot.enabled

    bot.toggle.side_effect = _toggle
    return bot


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'toggle_test.db').as_posix()}"


@pytest.fixture
def running_server(db_url, tmp_path):
    """Spin up a real DashboardServer on an OS-assigned free port."""
    bot = _make_bot(db_url)
    SettingsStore(
        db_url=db_url,
        creator_id=bot.creator_id,
    ).create_table()
    guidance = ChatGuidanceService(
        SettingsStore(
            engine=bot.note_repo.engine,
            creator_id=bot.creator_id,
        ),
        legacy_brand_bible_path=tmp_path / "brand_bible.md",
    )
    inbound_wakeup = MagicMock()
    server = DashboardServer(
        bot,
        port=0,
        dashboard_user=TEST_USER,
        dashboard_password=TEST_PASSWORD,
        csrf_token=TEST_CSRF_TOKEN,
        apifansly_webhook_token=TEST_WEBHOOK_TOKEN,
        onlyfansapi_webhook_secret=(
            TEST_ONLYFANSAPI_WEBHOOK_SECRET
        ),
        inbound_wakeup=inbound_wakeup,
        persona_dir=str(tmp_path / "personas"),
        brand_bible_path=str(tmp_path / "brand_bible.md"),
        ai_settings=bot.ai_settings,
        chat_guidance=guidance,
        webhook_endpoint_url=(
            "https://bot.example/webhooks/onlyfansapi/fansly"
        ),
        webhook_registration_enabled=False,
    )
    port = server.server.server_address[1]

    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()

    yield f"127.0.0.1:{port}", bot, db_url

    server.shutdown()
    thread.join(timeout=2)


class TestApifanslyPurchaseWebhook:
    def _payload(self):
        return {
            "accountId": "fansly_acc_test",
            "event": "ppv.purchased",
            "timestamp": "2026-06-23T18:11:59.242Z",
            "data": {
                "orderId": "order-1",
                "accountMediaId": "account-media-1",
                "correlationAccountId": "creator-native-1",
                "accountId": "fan-1",
                "type": 1,
                "orderMetadata": {
                    "accountMediaPrice": 1000,
                },
            },
        }

    def test_exact_purchase_advances_without_dashboard_auth(
        self,
        running_server,
    ):
        host, bot, _ = running_server

        status, body = _post_webhook(
            host,
            TEST_WEBHOOK_TOKEN,
            self._payload(),
        )

        assert status == 200
        assert body == {"accepted": True, "duplicate": False}
        bot.record_provider_ppv_purchase.assert_called_once()
        kwargs = bot.record_provider_ppv_purchase.call_args.kwargs
        assert kwargs["provider_purchase_id"] == "order-1"
        assert kwargs["provider_purchase_ref"] == "account-media-1"
        assert kwargs["fan_id"] == "fan-1"
        assert kwargs["amount_millis"] == 10_000

    def test_wrong_route_token_is_not_exposed(
        self,
        running_server,
    ):
        host, bot, _ = running_server

        status, body = _post_webhook(
            host,
            "wrong-token",
            self._payload(),
        )

        assert status == 404
        assert body == {"error": "not found"}
        bot.record_provider_ppv_purchase.assert_not_called()

    def test_account_mismatch_is_rejected(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["accountId"] = "different-account"

        status, _ = _post_webhook(
            host,
            TEST_WEBHOOK_TOKEN,
            payload,
        )

        assert status == 403
        bot.record_provider_ppv_purchase.assert_not_called()


class TestOnlyFansApiFanslyWebhook:
    def _payload(self):
        return {
            "event": "fansly.messages.received",
            "account_id": "fansly_acc_test",
            "payload": {
                "id": "message-1",
                "groupId": "chat-1",
                "senderId": "fan-1",
                "content": "hey",
                "createdAt": 1_722_000_000,
            },
        }

    def test_signed_message_is_enqueued_without_dashboard_auth(
        self,
        running_server,
    ):
        host, bot, _ = running_server

        status, body = _post_onlyfansapi_webhook(
            host,
            self._payload(),
        )

        assert status == 200
        assert body == {"accepted": True, "duplicate": False}
        bot.ingest_webhook_message.assert_called_once()
        event = bot.ingest_webhook_message.call_args.args[0]
        assert event.platform_message_id == "message-1"
        assert event.chat_id == "chat-1"
        assert event.fan_id == "fan-1"

    def test_signed_gateway_uses_startup_cached_provider_identity(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.account_id = "must-not-be-read-in-request"
        bot.client.creator_fansly_id = "must-not-be-read-in-request"

        status, body = _post_onlyfansapi_webhook(
            host,
            self._payload(),
        )

        assert status == 200
        assert body == {"accepted": True, "duplicate": False}
        bot.ingest_webhook_message.assert_called_once()

    def test_invalid_signature_is_rejected_before_ingestion(
        self,
        running_server,
    ):
        host, bot, _ = running_server

        status, body = _post_onlyfansapi_webhook(
            host,
            self._payload(),
            secret="wrong-signing-secret-with-enough-entropy",
        )

        assert status == 401
        assert body == {"error": "invalid signature"}
        bot.ingest_webhook_message.assert_not_called()

    def test_duplicate_event_is_acknowledged_idempotently(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.ingest_webhook_message.return_value = False

        status, body = _post_onlyfansapi_webhook(
            host,
            self._payload(),
        )

        assert status == 200
        assert body == {"accepted": True, "duplicate": True}

    def test_wrong_fansly_account_is_rejected(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["account_id"] = "fansly_acct_other"

        status, body = _post_onlyfansapi_webhook(host, payload)

        assert status == 403
        assert body == {"error": "webhook account mismatch"}
        bot.ingest_webhook_message.assert_not_called()

    def test_unknown_signed_event_is_quarantined_after_account_check(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["event"] = "fansly.future.event"

        status, body = _post_onlyfansapi_webhook(host, payload)

        assert status == 202
        assert body == {
            "accepted": False,
            "quarantined": True,
        }
        bot.webhook_event_repo.record_dead_letter.assert_called_once()
        bot.ingest_webhook_message.assert_not_called()

    def test_non_ready_handler_is_not_processed_early(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["event"] = "fansly.posts.created"

        status, body = _post_onlyfansapi_webhook(host, payload)

        assert status == 202
        assert body["quarantined"] is True
        kwargs = (
            bot.webhook_event_repo.record_dead_letter.call_args.kwargs
        )
        assert kwargs["error_category"] == "handler_not_ready"
        bot.ingest_webhook_message.assert_not_called()

    def test_signed_creator_message_uses_sent_projection(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["event"] = "fansly.messages.sent"
        payload["payload"]["senderId"] = "creator-native-1"
        payload["payload"]["recipientId"] = "fan-1"

        status, body = _post_onlyfansapi_webhook(host, payload)

        assert status == 200
        assert body == {"accepted": True, "duplicate": False}
        bot.ingest_webhook_sent.assert_called_once()
        bot.ingest_webhook_message.assert_not_called()

    def test_signed_revenue_event_projects_without_contact_work(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["event"] = "fansly.tips.received"
        payload["payload"] = {
            "id": "tip-1",
            "fanId": "fan-1",
            "amount": "12.34",
            "currency": "USD",
            "createdAt": 1_722_000_000,
        }

        status, body = _post_onlyfansapi_webhook(host, payload)

        assert status == 200
        assert body == {"accepted": True, "duplicate": False}
        bot.ingest_webhook_domain.assert_called_once()
        bot.ingest_webhook_message.assert_not_called()

    def test_quarantine_database_failure_remains_retryable(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = self._payload()
        payload["event"] = "fansly.future.event"
        bot.webhook_event_repo.record_dead_letter.side_effect = (
            RuntimeError("database unavailable")
        )

        status, body = _post_onlyfansapi_webhook(host, payload)

        assert status == 503
        assert body == {
            "error": "webhook persistence unavailable"
        }


class TestWebhookControlCenter:
    def test_authenticated_status_is_sanitized_and_lists_all_handlers(
        self,
        running_server,
    ):
        host, _, _ = running_server

        status, body = _get(host, "/api/webhooks/control")

        assert status == 200
        assert body["registration_enabled"] is False
        assert len(body["desired_events"]) == 14
        assert len(body["handler_readiness"]) == 25
        serialized = json.dumps(body)
        assert TEST_ONLYFANSAPI_WEBHOOK_SECRET not in serialized
        assert "signing_secret" not in serialized

    def test_reconcile_is_blocked_while_deployment_gate_is_false(
        self,
        running_server,
    ):
        host, bot, _ = running_server

        status, body = _post(host, "/api/webhooks/reconcile", {})

        assert status == 409
        assert "disabled by deployment policy" in body["error"]
        bot.client.ensure_fansly_webhook.assert_not_called()

    def test_explicit_health_check_compares_zero_credit_live_catalog(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.list_available_webhook_events.return_value = {
            "events": [
                {
                    "value": spec.name,
                    "description": spec.description,
                }
                for spec in EVENT_REGISTRY.values()
            ],
            "credits_used": 0,
        }

        status, body = _post(
            host,
            "/api/webhooks/health-check",
            {},
        )

        assert status == 200
        assert body["healthy"] is True
        assert body["catalog_event_count"] == 25
        assert body["catalog_credits_used"] == 0
        bot.client.list_available_webhook_events.assert_called_once()


class TestBotStatusEndpoints:
    """/health and /api/bot/status must reflect the live in-memory state —
    this is what the dashboard toggle pill polls to render its own state."""

    def test_health_is_public_and_minimal(self, running_server):
        host, _, _ = running_server
        status, body = _get(host, "/health", authenticated=False)
        assert status == 200
        assert body == {"status": "ok", "service": "fansly-bot"}

    def test_ready_is_public_and_checks_database(self, running_server):
        host, _, _ = running_server

        status, body = _get(host, "/ready", authenticated=False)

        assert status == 200
        assert body == {"status": "ready", "service": "fansly-bot"}

    def test_ready_fails_when_database_is_unavailable(self):
        server = DashboardServer(
            None,
            port=0,
            dashboard_user=TEST_USER,
            dashboard_password=TEST_PASSWORD,
        )
        port = server.server.server_address[1]
        thread = threading.Thread(
            target=server.server.serve_forever,
            daemon=True,
        )
        thread.start()
        try:
            status, body = _get(
                f"127.0.0.1:{port}",
                "/ready",
                authenticated=False,
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)

        assert status == 503
        assert body == {
            "status": "not_ready",
            "service": "fansly-bot",
        }

    def test_operations_requires_auth_and_reports_pipeline(
        self,
        running_server,
    ):
        host, _, _ = running_server

        status, _ = _get(
            host,
            "/api/operations",
            authenticated=False,
        )
        assert status == 401

        status, body = _get(host, "/api/operations")
        assert status == 200
        assert body["database_ready"] is True
        assert body["bot"]["available"] is True
        assert isinstance(body["pipeline"], dict)
        assert body["crm_sync"] == {
            "discovered_chats": 0,
            "complete_chats": 0,
            "pending_chats": 0,
            "failed_chats": 0,
            "stored_messages": 0,
        }

    def test_bot_status_reflects_enabled_state(self, running_server):
        host, bot, _ = running_server
        bot.enabled = False
        bot.enable_stalled_outreach = True
        status, body = _get(host, "/api/bot/status")
        assert status == 200
        assert body["available"] is True
        assert body["enabled"] is False
        assert body["persisted_enabled"] is None
        assert body["consistent"] is True
        assert body["stalled_outreach"] is True

    def test_empty_controlled_launch_rejects_enable(self, running_server):
        host, bot, db_url = running_server
        bot.enabled = False
        bot.require_fan_allowlist = True
        bot.allowed_fan_ids = frozenset()
        bot.launch_ready = False
        bot.launch_block_reason = (
            "controlled launch requires at least one FAN_ALLOWLIST entry"
        )
        bot.toggle.side_effect = LaunchGuardError(
            bot.launch_block_reason
        )

        status, body = _post(host, "/api/bot/toggle", {"enabled": True})

        assert status == 409
        assert "FAN_ALLOWLIST" in body["error"]
        assert SettingsStore(
            db_url=db_url,
            creator_id=bot.creator_id,
        ).get("bot_enabled") == "false"

    def test_connection_check_is_post_only(self, running_server):
        host, bot, _ = running_server

        status, body = _get(host, "/api/connection?test=1")

        assert status == 200
        assert body["connected"] is True
        bot.client.list_chats.assert_not_called()

        status, body = _post(host, "/api/connection/test", {})

        assert status == 200
        assert body["connected"] is True
        assert body["status"] == "live_verified"
        bot.client.verify_auth.assert_called_once_with()
        bot.client.list_chats.assert_not_called()

        status, persisted = _get(host, "/api/connection")
        assert status == 200
        assert persisted["status"] == "live_verified"
        assert persisted["live_checked"] is True

    def test_failed_live_connection_check_updates_truthful_status(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.verify_auth.side_effect = RuntimeError(
            "provider unavailable"
        )

        status, body = _post(host, "/api/connection/test", {})

        assert status == 200
        assert body["connected"] is False
        assert body["status"] == "offline"
        assert body["error"] == "provider unavailable"

        status, persisted = _get(host, "/api/connection")
        assert status == 200
        assert persisted["connected"] is False
        assert persisted["status"] == "offline"

    def test_ai_settings_never_return_api_key(self, running_server):
        host, _, _ = running_server

        status, body = _get(host, "/api/ai/settings")

        assert status == 200
        assert body["configured"] is True
        assert body["model"] == "deepseek-v4-flash"
        assert "api_key" not in body

    def test_ai_key_is_passed_to_server_only_on_save(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        api_key = "deepseek-secret-value-with-enough-length"

        status, body = _post(
            host,
            "/api/ai/settings",
            {
                "api_key": api_key,
                "model": "deepseek-v4-flash",
            },
        )

        assert status == 200
        assert "api_key" not in body
        bot.ai_settings.save.assert_called_once_with(
            api_key=api_key,
            model="deepseek-v4-flash",
        )

    def test_ai_key_save_requires_csrf(self, running_server):
        host, bot, _ = running_server

        status, body = _post(
            host,
            "/api/ai/settings",
            {
                "api_key": "deepseek-secret-value-with-enough-length",
                "model": "deepseek-v4-flash",
            },
            csrf=False,
        )

        assert status == 403
        assert body == {
            "error": "invalid CSRF token or request origin"
        }
        bot.ai_settings.save.assert_not_called()

    def test_ai_connection_test_uses_saved_credential(
        self,
        running_server,
    ):
        host, bot, _ = running_server

        status, body = _post(
            host,
            "/api/ai/connection/test",
            {},
        )

        assert status == 200
        assert body["last_test_ok"] is True
        assert "api_key" not in body
        bot.ai_settings.test_connection.assert_called_once_with()


class TestCrmConversationHistory:
    def test_all_provider_messages_are_available_through_pagination(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.state_repo.ensure_conversation(
            bot.creator_id,
            "fan-1",
            "chat-1",
            display_name="Fan One",
            username="fan_one",
        )
        sync_repo = CrmSyncRepository(bot.state_repo.engine)
        sync_repo.discover_chat(
            creator_id=bot.creator_id,
            chat_id="chat-1",
            fan_id="fan-1",
            provider_head_message_id="message-204",
        )
        sync_repo.complete_initial_page(
            creator_id=bot.creator_id,
            chat_id="chat-1",
            provider_head_message_id="message-204",
            backfill_cursor=None,
        )
        started = datetime(2026, 7, 1, tzinfo=timezone.utc)
        for index in range(205):
            bot.message_store.save_message(
                "fan-1",
                bot.creator_id,
                "fan" if index % 2 == 0 else "creator",
                f"message {index}",
                message_id=f"message-{index}",
                chat_id="chat-1",
                attachments=[],
                created_at=started + timedelta(minutes=index),
            )

        status, listing = _get(host, "/api/conversations")
        assert status == 200
        assert listing["fans"][0]["username"] == "fan_one"
        assert listing["fans"][0]["message_count"] == 205
        assert listing["fans"][0]["history_complete"] is True

        status, newest = _get(
            host,
            "/api/conversations/fan-1?limit=100&offset=0",
        )
        assert status == 200
        assert newest["message_count_stored"] == 205
        assert newest["has_more_messages"] is True
        assert newest["profile"]["username"] == "fan_one"
        assert len(newest["messages"]) == 100
        assert newest["messages"][0]["content"] == "message 105"
        assert newest["messages"][-1]["content"] == "message 204"

        status, oldest = _get(
            host,
            "/api/conversations/fan-1?limit=100&offset=200",
        )
        assert status == 200
        assert oldest["has_more_messages"] is False
        assert [row["content"] for row in oldest["messages"]] == [
            f"message {index}"
            for index in range(5)
        ]

    def test_empty_inbox_never_reads_provider_during_navigation(self, db_url):
        bot = _make_bot(db_url)
        sync = MagicMock()
        server = DashboardServer(
            bot,
            port=0,
            crm_sync=sync,
            dashboard_user=TEST_USER,
            dashboard_password=TEST_PASSWORD,
            csrf_token=TEST_CSRF_TOKEN,
        )
        port = server.server.server_address[1]
        thread = threading.Thread(
            target=server.server.serve_forever,
            daemon=True,
        )
        thread.start()
        try:
            status, body = _get(
                f"127.0.0.1:{port}",
                "/api/conversations?limit=50",
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)

        assert status == 200
        assert body["total"] == 0
        assert body["has_more"] is False
        assert body["provider_primed"] is False
        assert body["live_sync_available"] is True
        assert body["fans"] == []
        sync.refresh_chat_index.assert_not_called()
        sync.hydrate_recent.assert_not_called()

    def test_opening_conversation_reads_only_stored_messages(
        self,
        db_url,
    ):
        bot = _make_bot(db_url)
        bot.state_repo.ensure_conversation(
            bot.creator_id,
            "fan-live",
            "chat-live",
            display_name="Live Fan",
            username="live_fan",
        )
        CrmSyncRepository(bot.state_repo.engine).discover_chat(
            creator_id=bot.creator_id,
            chat_id="chat-live",
            fan_id="fan-live",
            provider_head_message_id="message-live",
        )
        sync = MagicMock()
        bot.message_store.save_message(
            "fan-live",
            bot.creator_id,
            "fan",
            "already stored",
            message_id="message-live",
            chat_id="chat-live",
        )
        server = DashboardServer(
            bot,
            port=0,
            crm_sync=sync,
            dashboard_user=TEST_USER,
            dashboard_password=TEST_PASSWORD,
            csrf_token=TEST_CSRF_TOKEN,
        )
        port = server.server.server_address[1]
        thread = threading.Thread(
            target=server.server.serve_forever,
            daemon=True,
        )
        thread.start()
        try:
            status, body = _get(
                f"127.0.0.1:{port}",
                "/api/conversations/fan-live?limit=100&offset=0",
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)

        assert status == 200
        assert body["live_hydrated"] is False
        assert body["live_sync_available"] is True
        assert body["live_refresh_error"] is None
        assert body["messages"][0]["content"] == "already stored"
        sync.hydrate_recent.assert_not_called()


class TestDashboardSecurity:
    def test_dashboard_requires_authentication(self, running_server):
        host, _, _ = running_server
        status, body, headers = _request(host, "GET", "/")

        assert status == 401
        assert body == {"error": "authentication required"}
        assert headers["www-authenticate"].startswith("Basic ")

    def test_api_requires_authentication(self, running_server):
        host, _, _ = running_server
        status, body = _get(host, "/api/bot/status", authenticated=False)

        assert status == 401
        assert body == {"error": "authentication required"}

    def test_wrong_password_is_rejected(self, running_server):
        host, _, _ = running_server
        status, body, _ = _request(
            host,
            "GET",
            "/",
            headers={"Authorization": _authorization(password="wrong-password-value")},
        )

        assert status == 401
        assert body == {"error": "authentication required"}

    def test_dashboard_sets_security_headers_and_embeds_nonce(self, running_server):
        host, _, _ = running_server
        status, body, headers = _request(
            host,
            "GET",
            "/",
            headers={"Authorization": _authorization()},
        )

        assert status == 200
        assert headers["cache-control"] == "no-store"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"
        assert "access-control-allow-origin" not in headers
        csp = headers["content-security-policy"]
        nonce_match = re.search(r"script-src 'nonce-([^']+)'", csp)
        assert nonce_match is not None
        nonce = nonce_match.group(1)
        assert f'<script nonce="{nonce}">' in body
        assert f'<style nonce="{nonce}">' in body
        assert f'const CSRF_TOKEN="{TEST_CSRF_TOKEN}";' in body

    def test_mutation_requires_csrf_token(self, running_server):
        host, bot, _ = running_server
        bot.enabled = True

        status, body = _post(
            host,
            "/api/bot/toggle",
            {"enabled": False},
            csrf=False,
        )

        assert status == 403
        assert body == {"error": "invalid CSRF token or request origin"}
        assert bot.enabled is True

    def test_mutation_rejects_cross_site_origin(self, running_server):
        host, bot, _ = running_server
        bot.enabled = True

        status, body = _post(
            host,
            "/api/bot/toggle",
            {"enabled": False},
            origin="https://attacker.example",
        )

        assert status == 403
        assert body == {"error": "invalid CSRF token or request origin"}
        assert bot.enabled is True

    def test_invalid_host_is_rejected(self, running_server):
        host, _, _ = running_server
        status, body, _ = _request(
            host,
            "GET",
            "/health",
            headers={"Host": "attacker.example"},
        )

        assert status == 400
        assert body == {"error": "invalid host"}

    def test_railway_healthcheck_host_can_only_reach_probes(
        self,
        running_server,
    ):
        host, _, _ = running_server

        status, body, _ = _request(
            host,
            "GET",
            "/health",
            headers={"Host": "healthcheck.railway.app"},
        )
        assert status == 200
        assert body == {"status": "ok", "service": "fansly-bot"}

        status, body, _ = _request(
            host,
            "GET",
            "/ready",
            headers={"Host": "healthcheck.railway.app"},
        )
        assert status == 200
        assert body == {"status": "ready", "service": "fansly-bot"}

        status, body, _ = _request(
            host,
            "GET",
            "/",
            headers={
                "Host": "healthcheck.railway.app",
                "Authorization": _authorization(),
            },
        )
        assert status == 400
        assert body == {"error": "invalid host"}

    def test_creator_path_traversal_is_rejected(
        self, running_server, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("src.web.dashboard.PERSONA_DIR", str(tmp_path))
        host, _, _ = running_server

        status, body = _get(host, "/api/persona?creator=..%2F..%2Fsecret")

        assert status == 400
        assert body == {"error": "invalid creator id"}

    def test_oversized_body_is_rejected(self, running_server):
        host, _, _ = running_server
        conn = HTTPConnection(host, timeout=5)
        conn.putrequest("POST", "/api/brand-bible")
        conn.putheader("Authorization", _authorization())
        conn.putheader("X-CSRF-Token", TEST_CSRF_TOKEN)
        conn.putheader("Origin", f"http://{host}")
        conn.putheader("Content-Type", "text/markdown")
        conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
        conn.endheaders()
        response = conn.getresponse()
        status = response.status
        body = json.loads(response.read())
        conn.close()

        assert status == 413
        assert body == {"error": "request body too large"}

    def test_missing_server_credentials_fail_closed(self, db_url):
        server = DashboardServer(
            _make_bot(db_url),
            port=0,
            dashboard_user="",
            dashboard_password="",
        )
        port = server.server.server_address[1]
        thread = threading.Thread(target=server.server.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _get(f"127.0.0.1:{port}", "/")
            assert status == 503
            assert body == {"error": "dashboard credentials are not configured"}
        finally:
            server.shutdown()
            thread.join(timeout=2)


class TestBotToggleEndpoint:
    """/api/bot/toggle is the only write path for the switch — it must both
    flip the in-process bot AND persist to the DB, since main.py re-reads the
    DB value on every restart/redeploy (the bug class this guards against:
    a toggle that "worked" in the UI but silently reverted on next deploy)."""

    def test_toggle_off_flips_bot_and_persists(self, running_server):
        host, bot, url = running_server
        bot.enabled = True

        status, body = _post(host, "/api/bot/toggle", {"enabled": False})

        assert status == 200
        assert body["enabled"] is False
        assert body["persisted_enabled"] is False
        assert body["consistent"] is True
        assert bot.enabled is False
        assert SettingsStore(
            db_url=url,
            creator_id=bot.creator_id,
        ).get("bot_enabled") == "false"

    def test_toggle_on_flips_bot_and_persists(self, running_server):
        host, bot, url = running_server
        bot.enabled = False

        status, body = _post(host, "/api/bot/toggle", {"enabled": True})

        assert status == 200
        assert body["enabled"] is True
        assert body["persisted_enabled"] is True
        assert body["consistent"] is True
        assert bot.enabled is True
        assert SettingsStore(
            db_url=url,
            creator_id=bot.creator_id,
        ).get("bot_enabled") == "true"

    def test_toggle_with_no_body_flips_current_state(self, running_server):
        host, bot, _ = running_server
        bot.enabled = True

        status, body = _post(host, "/api/bot/toggle")

        assert status == 200
        assert body["enabled"] is False
        assert body["persisted_enabled"] is False
        assert bot.enabled is False

    def test_toggle_persists_across_settings_store_instances(self, running_server):
        """Simulates a redeploy: main.py constructs a *fresh* SettingsStore on
        startup and reads bot_enabled from it — this is the actual mechanism
        that must survive a restart, not just the in-memory bot.enabled flag."""
        host, bot, url = running_server

        _post(host, "/api/bot/toggle", {"enabled": False})

        fresh_store = SettingsStore(
            db_url=url,
            creator_id=bot.creator_id,
        )
        assert fresh_store.get("bot_enabled", "true").lower() == "false"

    def test_toggle_without_bot_returns_503(self, db_url):
        server = DashboardServer(
            None,
            port=0,
            dashboard_user=TEST_USER,
            dashboard_password=TEST_PASSWORD,
            csrf_token=TEST_CSRF_TOKEN,
        )
        port = server.server.server_address[1]
        thread = threading.Thread(target=server.server.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _post(f"127.0.0.1:{port}", "/api/bot/toggle", {"enabled": False})
            assert status == 503
            assert "error" in body
        finally:
            server.shutdown()
            thread.join(timeout=2)

    def test_non_boolean_target_is_rejected_without_state_change(
        self,
        running_server,
    ):
        host, bot, url = running_server
        bot.enabled = True

        status, body = _post(
            host,
            "/api/bot/toggle",
            {"enabled": "false"},
        )

        assert status == 400
        assert body == {"error": "enabled must be a boolean"}
        assert bot.enabled is True
        assert SettingsStore(
            db_url=url,
            creator_id=bot.creator_id,
        ).get("bot_enabled") is None

    def test_persistence_failure_does_not_change_runtime_state(
        self,
        running_server,
        monkeypatch,
    ):
        host, bot, _ = running_server
        bot.enabled = True

        def fail_set(self, key, value):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(SettingsStore, "set", fail_set)
        status, body = _post(
            host,
            "/api/bot/toggle",
            {"enabled": False},
        )

        assert status == 500
        assert body == {"error": "database unavailable"}
        assert bot.enabled is True
        bot.toggle.assert_not_called()


class TestTruthfulDashboardControls:
    def test_creator_script_override_crud_and_runtime_reload(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = {
            "name": "welcome_evening",
            "category": "welcome",
            "description": "Evening greeting",
            "messages": [
                "hey {fan_name}",
                "how was your evening?",
            ],
            "is_active": True,
        }

        status, created = _post(host, "/api/scripts", payload)

        assert status == 200
        assert created["script"]["name"] == "welcome_evening"
        assert created["script"]["variables"] == [
            {
                "name": "fan_name",
                "source": "fan_notes.display_name",
                "fallback": "friend",
            }
        ]
        script_id = created["script"]["id"]
        bot.reload_scripts.assert_called_once_with()

        status, listing = _get(host, "/api/scripts")
        assert status == 200
        saved = next(
            script
            for script in listing["scripts"]
            if script["name"] == "welcome_evening"
        )
        assert saved["origin"] == "custom"
        assert saved["messages"] == payload["messages"]

        payload["description"] = "Updated greeting"
        status, updated = _post(
            host,
            f"/api/scripts/{script_id}",
            payload,
        )
        assert status == 200
        assert updated["script"]["description"] == "Updated greeting"

        status, deleted = _delete(
            host,
            f"/api/scripts/{script_id}",
        )
        assert status == 200
        assert deleted["runtime_applied"] is True

    def test_invalid_script_is_rejected(self, running_server):
        host, _, _ = running_server

        status, body = _post(
            host,
            "/api/scripts",
            {
                "name": "not a valid id",
                "category": "welcome",
                "messages": [],
            },
        )

        assert status == 400
        assert "name must be" in body["error"]

    def test_media_registry_crud(self, running_server):
        host, _, _ = running_server
        payload = {
            "title": "Red dress teaser",
            "provider_media_id": "fansly_media_01JR1234",
            "account_media_id": "925889499706191874",
            "media_type": "video",
            "tags": ["red", "tease"],
            "thumbnail_url": "https://cdn3.fansly.com/example.jpeg",
        }

        status, created = _post(host, "/api/media-assets", payload)

        assert status == 200
        assert created["asset"]["provider_media_id"] == (
            "fansly_media_01JR1234"
        )
        asset_id = created["asset"]["id"]

        status, listing = _get(host, "/api/media-assets?query=red")
        assert status == 200
        assert listing["provider_listing_supported"] is True
        assert [asset["id"] for asset in listing["assets"]] == [
            asset_id
        ]

        status, deleted = _delete(
            host,
            f"/api/media-assets/{asset_id}",
        )
        assert status == 200
        assert deleted == {"status": "ok"}

    def test_media_registry_rejects_non_https_preview(
        self,
        running_server,
    ):
        host, _, _ = running_server

        status, body = _post(
            host,
            "/api/media-assets",
            {
                "title": "Unsafe preview",
                "provider_media_id": "fansly_media_safe",
                "thumbnail_url": "javascript:alert(1)",
            },
        )

        assert status == 400
        assert body["error"] == "thumbnail_url must be an HTTPS URL"

    def test_kpis_use_durable_events_and_report_unavailable_values(
        self,
        running_server,
    ):
        host, _, _ = running_server

        status, body = _get(host, "/api/kpis")

        assert status == 200
        assert body["source"] == "durable_attributed_events"
        assert body["sent_outbounds"] == 0
        assert body["attributed_purchases"] == 0
        assert body["attributed_revenue"] == 0
        assert body["ppv_unlock_rate"] is None
        assert body["chatting_ratio"] is None
        assert body["script_completion_rate"] is None

    def test_vault_endpoints_report_provider_capability(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.capabilities = ProviderCapabilities()

        status, albums = _get(host, "/api/vault-albums")
        assert status == 200
        assert albums["supported"] is False
        assert albums["albums"] == []
        assert "cannot browse vault albums" in albums["reason"]
        bot.client.list_albums.assert_not_called()

        status, media = _get(
            host,
            "/api/vault-albums/example/media",
        )
        assert status == 200
        assert media["supported"] is False
        assert media["media"] == []
        bot.client.get_album_media.assert_not_called()

    def test_active_sequence_is_rejected_when_paid_send_is_unsupported(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.capabilities = ProviderCapabilities()
        payload = {
            "name": "Draft ladder",
            "trigger": "welcome",
            "funnel_stage": "offer",
            "is_active": True,
            "steps": [
                {
                    "media_id": "fansly_media_1",
                    "preview_id": "preview_media_1",
                    "price": 10,
                    "tease_script": "look",
                    "offer_script": "unlock",
                }
            ],
        }

        status, body = _post(host, "/api/sequences", payload)

        assert status == 409
        assert "does not support paid" in body["error"]
        assert bot.sequence_repo.list_sequences() == []

    def test_inactive_sequence_draft_is_validated_and_saved(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.capabilities = ProviderCapabilities()
        payload = {
            "name": "Draft ladder",
            "trigger": "welcome",
            "funnel_stage": "offer",
            "is_active": False,
            "steps": [
                {
                    "media_id": "fansly_media_1",
                    "preview_id": "preview_media_1",
                    "price": 10,
                    "tease_script": "look",
                    "offer_script": "unlock",
                }
            ],
        }

        status, created = _post(host, "/api/sequences", payload)

        assert status == 200
        saved = bot.sequence_repo.get_sequence(created["id"])
        assert saved.is_active is False
        assert saved.steps[0].media_id == "fansly_media_1"
        assert saved.steps[0].preview_id == "preview_media_1"

        status, listing = _get(host, "/api/sequences")
        assert status == 200
        assert listing["paid_messages_supported"] is False
        assert listing["editing_available"] is True
        assert listing["sequences"][0]["effective_active"] is False

    def test_sequence_read_and_delete_validate_resource_id(
        self,
        running_server,
    ):
        host, _, _ = running_server

        status, _ = _get(host, "/api/sequences/not-a-number")
        assert status == 400

        status, body = _delete(host, "/api/sequences/999999")
        assert status == 404
        assert body["error"] == "not found"

    def test_invalid_provider_media_id_is_not_saved(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        payload = {
            "name": "Invalid draft",
            "trigger": "welcome",
            "funnel_stage": "offer",
            "is_active": False,
            "steps": [
                {
                    "media_id": "local-file.mp4",
                    "price": 10,
                }
            ],
        }

        status, body = _post(host, "/api/sequences", payload)

        assert status == 400
        assert "valid provider media ID" in body["error"]
        assert bot.sequence_repo.list_sequences() == []

    def test_existing_active_sequence_is_shown_as_blocked(
        self,
        running_server,
    ):
        host, bot, _ = running_server
        bot.client.capabilities = ProviderCapabilities()
        sequence = Sequence(
            name="Legacy active",
            trigger=SequenceTrigger.WELCOME,
            funnel_stage="offer",
            is_active=True,
            steps=[
                SequenceStep(
                    sequence_id=0,
                    position=1,
                    media_id="fansly_media_1",
                    price=10,
                )
            ],
        )
        bot.sequence_repo.save_sequence_with_steps(sequence)

        status, body = _get(host, "/api/sequences")

        assert status == 200
        item = body["sequences"][0]
        assert item["is_active"] is True
        assert item["effective_active"] is False
        assert item["blocked_reason"]

    def test_persona_save_is_validated_and_applied_to_running_bot(
        self,
        running_server,
        tmp_path,
    ):
        host, bot, _ = running_server
        payload = {
            "tone": "warm",
            "signature_phrases": ["hey"],
            "forbidden_phrases": ["as an ai"],
            "emoji_style": "light",
            "sentence_style": "short",
        }

        status, body = _post(
            host,
            "/api/persona?creator=test_creator",
            payload,
        )

        assert status == 200
        assert body["saved"] is True
        assert body["runtime_applied"] is True
        assert (
            tmp_path / "personas" / "test_creator.yaml"
        ).exists()
        bot.reload_persona.assert_called_once_with()

        status, loaded = _get(
            host,
            "/api/persona?creator=test_creator",
        )
        assert status == 200
        assert loaded["persona"]["tone"] == "warm"
        assert loaded["persona"]["signature_phrases"] == ["hey"]

    def test_invalid_persona_is_not_saved(
        self,
        running_server,
        tmp_path,
    ):
        host, bot, _ = running_server

        status, body = _post(
            host,
            "/api/persona?creator=test_creator",
            {"tone": "missing required fields"},
        )

        assert status == 400
        assert "error" in body
        assert not (
            tmp_path / "personas" / "test_creator.yaml"
        ).exists()
        bot.reload_persona.assert_not_called()

    def test_chat_instructions_and_brand_bible_are_live_database_settings(
        self,
        running_server,
    ):
        host, _, db_url = running_server

        status, chat_body = _post_text(
            host,
            "/api/chat-instructions",
            "Reply directly and ask one natural question.",
        )
        bible_status, bible_body = _post_text(
            host,
            "/api/brand-bible",
            "Sunny is playful and warm.",
            content_type="text/markdown; charset=utf-8",
        )

        assert status == 200
        assert bible_status == 200
        assert chat_body["saved"] is True
        assert chat_body["runtime_applied"] is True
        assert chat_body["storage"] == "database"
        assert bible_body["saved"] is True
        assert bible_body["runtime_applied"] is True
        assert bible_body["storage"] == "database"

        chat_get_status, chat_get = _get(
            host,
            "/api/chat-instructions",
        )
        bible_get_status, bible_get = _get(
            host,
            "/api/brand-bible",
        )
        assert chat_get_status == 200
        assert bible_get_status == 200
        assert chat_get["max_characters"] == 50_000
        assert chat_get["content"] == (
            "Reply directly and ask one natural question."
        )
        assert bible_get["content"] == "Sunny is playful and warm."

        stored = SettingsStore(
            db_url=db_url,
            creator_id="test_creator",
        )
        assert stored.get_scoped(
            "conversation.chat_instructions"
        ) == "Reply directly and ask one natural question."
        assert stored.get_scoped(
            "conversation.brand_bible"
        ) == "Sunny is playful and warm."
