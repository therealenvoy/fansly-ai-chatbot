"""Tests for the dashboard's bot on/off switch — /health, /api/bot/status,
/api/bot/toggle. This is the only control surface for enabling/disabling the
live bot, so it's tested against a real HTTPServer and a real (temp-file)
SettingsStore rather than mocked end-to-end, to catch real persistence bugs.
"""
import json
import threading
from http.client import HTTPConnection
from unittest.mock import MagicMock

import pytest

from src.settings.store import SettingsStore
from src.web.dashboard import DashboardServer, DashboardHandler


def _get(host, path):
    conn = HTTPConnection(host, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = json.loads(resp.read())
    conn.close()
    return resp.status, body


def _post(host, path, payload=None):
    conn = HTTPConnection(host, timeout=5)
    body = json.dumps(payload) if payload is not None else ""
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    return resp.status, data


def _make_bot(db_url):
    """A MagicMock bot with real toggle() semantics and a real DB url for
    _bot_toggle's SettingsStore(db_url=...) reconstruction to use."""
    bot = MagicMock()
    bot.enabled = True
    bot.creator_id = "test_creator"
    # note_repo.engine.url as a plain string takes the `str(...)` fallback
    # branch in dashboard.py's _bot_toggle (no render_as_string attribute).
    bot.note_repo.engine.url = db_url

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
    server = DashboardServer(bot, port=0)
    port = server.server.server_address[1]

    thread = threading.Thread(target=server.server.serve_forever, daemon=True)
    thread.start()

    yield f"127.0.0.1:{port}", bot, db_url

    server.shutdown()
    thread.join(timeout=2)


class TestBotStatusEndpoints:
    """/health and /api/bot/status must reflect the live in-memory state —
    this is what the dashboard toggle pill polls to render its own state."""

    def test_health_reflects_enabled_true(self, running_server):
        host, bot, _ = running_server
        bot.enabled = True
        status, body = _get(host, "/health")
        assert status == 200
        assert body["bot_enabled"] is True

    def test_health_reflects_enabled_false(self, running_server):
        host, bot, _ = running_server
        bot.enabled = False
        status, body = _get(host, "/health")
        assert status == 200
        assert body["bot_enabled"] is False

    def test_bot_status_reflects_enabled_state(self, running_server):
        host, bot, _ = running_server
        bot.enabled = False
        status, body = _get(host, "/api/bot/status")
        assert status == 200
        assert body == {"enabled": False}


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
        assert SettingsStore(db_url=url).get("bot_enabled") == "false"

    def test_toggle_on_flips_bot_and_persists(self, running_server):
        host, bot, url = running_server
        bot.enabled = False

        status, body = _post(host, "/api/bot/toggle", {"enabled": True})

        assert status == 200
        assert body == {"enabled": True}
        assert bot.enabled is True
        assert SettingsStore(db_url=url).get("bot_enabled") == "true"

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

        fresh_store = SettingsStore(db_url=url)
        assert fresh_store.get("bot_enabled", "true").lower() == "false"

    def test_toggle_without_bot_returns_503(self, db_url):
        server = DashboardServer(MagicMock(), port=0)
        DashboardHandler.bot = None
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
