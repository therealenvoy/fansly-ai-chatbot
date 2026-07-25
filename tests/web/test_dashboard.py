"""Tests for the dashboard's bot on/off switch — /health, /api/bot/status,
/api/bot/toggle. This is the only control surface for enabling/disabling the
live bot, so it's tested against a real HTTPServer and a real (temp-file)
SettingsStore rather than mocked end-to-end, to catch real persistence bugs.
"""
import json
import base64
import re
import threading
from http.client import HTTPConnection
from unittest.mock import MagicMock

import pytest

from src.settings.store import SettingsStore
from src.persistence.database import create_database_engine
from src.web.dashboard import DASHBOARD_HTML, MAX_BODY_BYTES, DashboardServer


TEST_USER = "test-operator"
TEST_PASSWORD = "correct-horse-battery-staple"
TEST_CSRF_TOKEN = "test-csrf-token-with-enough-entropy"


def _authorization(user=TEST_USER, password=TEST_PASSWORD):
    credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {credentials}"


class TestDashboardShell:
    """Regression checks for the responsive dashboard navigation."""

    def test_all_primary_destinations_are_semantic_buttons(self):
        for tab in ("funnel", "vault", "fans", "scripts", "kpis", "sequences", "settings"):
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

    def test_inline_event_handlers_are_not_used(self):
        assert " onclick=" not in DASHBOARD_HTML
        assert " onchange=" not in DASHBOARD_HTML


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


def _make_bot(db_url):
    """A MagicMock bot with real toggle() semantics and a real DB url for
    _bot_toggle's SettingsStore(db_url=...) reconstruction to use."""
    bot = MagicMock()
    bot.enabled = True
    bot.creator_id = "test_creator"
    bot.account_id = "account-123"
    bot.client.list_chats.return_value = []
    bot.note_repo.engine = create_database_engine(
        db_url,
        environment={"APP_ENV": "test"},
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
def running_server(db_url):
    """Spin up a real DashboardServer on an OS-assigned free port."""
    bot = _make_bot(db_url)
    server = DashboardServer(
        bot,
        port=0,
        dashboard_user=TEST_USER,
        dashboard_password=TEST_PASSWORD,
        csrf_token=TEST_CSRF_TOKEN,
    )
    port = server.server.server_address[1]

    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()

    yield f"127.0.0.1:{port}", bot, db_url

    server.shutdown()
    thread.join(timeout=2)


class TestBotStatusEndpoints:
    """/health and /api/bot/status must reflect the live in-memory state —
    this is what the dashboard toggle pill polls to render its own state."""

    def test_health_is_public_and_minimal(self, running_server):
        host, _, _ = running_server
        status, body = _get(host, "/health", authenticated=False)
        assert status == 200
        assert body == {"status": "ok", "service": "fansly-bot"}

    def test_bot_status_reflects_enabled_state(self, running_server):
        host, bot, _ = running_server
        bot.enabled = False
        status, body = _get(host, "/api/bot/status")
        assert status == 200
        assert body == {"enabled": False}

    def test_connection_check_is_post_only(self, running_server):
        host, bot, _ = running_server

        status, body = _get(host, "/api/connection?test=1")

        assert status == 200
        assert body["connected"] is True
        bot.client.list_chats.assert_not_called()

        status, body = _post(host, "/api/connection/test", {})

        assert status == 200
        assert body["connected"] is True
        bot.client.list_chats.assert_called_once_with(
            filter_type="all",
            sort="newest",
        )


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
        assert body == {"enabled": False}
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
        assert body == {"enabled": True}
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
        assert body == {"enabled": False}
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
