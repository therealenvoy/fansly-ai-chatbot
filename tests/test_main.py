"""Tests for main.py — startup auth validation, exponential backoff, credit logging.

Strategy: main.py has no __main__ guard — top-level code runs on import.
We patch low-level dependencies before first import, then control the
while loop via mock bot instances that self-terminate after N iterations.

Key: importlib.reload re-executes the entire module. During reload:
* FanslyClient(...) returns our pre-configured mock
* FanslyBot(...) returns our pre-configured mock with controlled poll_and_process
* time.sleep is globally patched to be a no-op
* The while loop terminates because poll_and_process sets running=False
"""
import logging
import os
import sys
import pytest
from unittest.mock import MagicMock, patch
import importlib

from src.fansly_client import AuthError, PaymentRequiredError, NotFoundError


# ─── Shared test helpers ─────────────────────────────────────────


def _make_controlled_bot(poll_side_effects=None, module_ref=None):
    """Create a bot whose poll_and_process runs through side_effects then stops.

    poll_side_effects: list of Exception (to raise) or None (success).
    module_ref: callable returning the main module (for setting running=False).
    """
    bot = MagicMock()
    bot.sequence_repo = MagicMock()

    if poll_side_effects is None:
        poll_side_effects = [None]

    iter_idx = [0]

    def _poll(*_args, **_kwargs):
        idx = iter_idx[0]
        iter_idx[0] += 1
        if idx >= len(poll_side_effects):
            mod = module_ref() if module_ref else sys.modules["src.main"]
            mod.running = False
            return
        result = poll_side_effects[idx]
        if isinstance(result, BaseException):
            raise result
        return result

    bot.poll_and_process = _poll
    return bot, iter_idx


def _make_note_repo():
    """Create a FanNoteRepository mock that bot.py can initialize with."""
    mock_url = MagicMock()
    mock_url.render_as_string.return_value = "sqlite:///:memory:"
    mock_engine = MagicMock()
    mock_engine.url = mock_url
    mock_inst = MagicMock()
    mock_inst.engine = mock_engine
    return mock_inst


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fast_time():
    """Make time.sleep a no-op so tests don't block."""
    def _sleep(_seconds):
        mod = sys.modules.get("src.main")
        if mod is not None and getattr(mod, "bot", object()) is None:
            mod.running = False

    with patch("time.sleep", side_effect=_sleep):
        yield


@pytest.fixture(autouse=True)
def _capture_info_logs(caplog):
    """main.py's logging.basicConfig(level=INFO) is a no-op under pytest — the
    root logger already has handlers from pytest's own logging plugin, whose
    default captured level is WARNING. Without this, INFO-level records (e.g.
    "API authentication verified") never reach caplog.records."""
    caplog.set_level(logging.INFO)


@pytest.fixture(autouse=True)
def cleanup_env():
    """Restore env after each test — prevents cross-test contamination."""
    saved = {k: os.environ.get(k) for k in (
        "APIFANSLY_API_KEY", "FANSLY_API_KEY",
        "FANSLY_ACCOUNT_ID", "APIFANSLY_WEBHOOK_TOKEN", "POLL_INTERVAL",
        "MAX_BACKOFF", "IDLE_BACKOFF_MAX", "FANSLY_PROVIDER",
        "DATABASE_URL", "PORT", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL",
        "CREDENTIAL_ENCRYPTION_KEY", "CREATOR_ID",
        "CONTROLLED_LAUNCH", "BOT_ENABLED_DEFAULT", "FAN_ALLOWLIST",
        "MAX_MESSAGES_PER_POLL", "CRM_SYNC_ENABLED",
        "BOT_MODE", "ENABLE_UNREAD_REPLIES",
        "ENABLE_ONLINE_OUTREACH", "ENABLE_STALLED_OUTREACH",
        "OUTREACH_EXISTING_ONLINE",
        "ONLINE_WINDOW_SECONDS", "PROACTIVE_COOLDOWN_HOURS",
        "MAX_PROACTIVE_PER_HOUR", "MAX_PROACTIVE_PER_DAY",
        "MAX_PROACTIVE_PER_FAN_PER_DAY", "PRESENCE_BATCH_SIZE",
        "PRESENCE_POLL_INTERVAL",
        "STALLED_AFTER_HOURS", "STALLED_SCAN_INTERVAL",
        "STALLED_SCAN_BATCH_SIZE",
        "CRM_SYNC_MESSAGE_PAGES_PER_CYCLE",
        "CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE",
        "CRM_SYNC_BACKFILL_INTERVAL",
    )}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def standard_env():
    """Normal env vars that let main.py initialize successfully."""
    os.environ["FANSLY_PROVIDER"] = "apifansly"
    os.environ["APIFANSLY_API_KEY"] = "test_key_123"
    os.environ["FANSLY_ACCOUNT_ID"] = "test_account_456"
    os.environ["APIFANSLY_WEBHOOK_TOKEN"] = "w" * 32
    os.environ.setdefault("POLL_INTERVAL", "1")
    os.environ.setdefault("MAX_BACKOFF", "8")
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("PORT", "19999")
    os.environ.setdefault("CREATOR_ID", "test_creator")
    os.environ["CONTROLLED_LAUNCH"] = "true"
    os.environ["BOT_ENABLED_DEFAULT"] = "false"
    os.environ["FAN_ALLOWLIST"] = "pilot-fan"
    os.environ["MAX_MESSAGES_PER_POLL"] = "5"
    os.environ["BOT_MODE"] = "full_ppv"
    os.environ["CRM_SYNC_ENABLED"] = "true"
    os.environ["CRM_SYNC_MESSAGE_PAGES_PER_CYCLE"] = "2"
    os.environ["CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE"] = "1"
    os.environ["CRM_SYNC_BACKFILL_INTERVAL"] = "1"


@pytest.fixture
def mock_deps(standard_env):
    """Patch low-level modules BEFORE src.main is imported."""
    # main.py's run_server() thread does `while running: dashboard.handle_request()`
    # with no throttle — fine in production, where handle_request() blocks on a
    # real socket. Here it's a MagicMock, so it returns instantly, and this test
    # never asserts anything about the dashboard — so don't let the thread run at
    # all: patching Thread.start makes server_thread.start() a no-op. (A real
    # thread spinning that unthrottled loop starves the main thread badly enough
    # under CPython's GIL on Windows to hang the whole test run — confirmed via
    # faulthandler.dump_traceback_later; even a 5ms Event().wait() throttle on
    # handle_request wasn't enough to unstick it.)
    patchers = [
        patch("threading.Thread.start", MagicMock()),
        patch("src.persona.loader.PersonaLoader.load",
              return_value=MagicMock()),
        patch("src.web.dashboard.DashboardServer", MagicMock()),
        patch("src.memory.store.MessageStore"),
        patch("src.memory.llm.LLMFactExtractor"),
        # bot.py __init__ dependencies
        patch("src.bot.SequenceRepository", MagicMock()),
        patch("src.bot.ScriptLibrary", MagicMock()),
        patch("src.bot.ScriptEngine", MagicMock()),
        patch("src.bot.NoteExtractor", MagicMock()),
        patch("src.bot.FanClassifier", MagicMock()),
        patch("src.bot.TierClassifier", MagicMock()),
        patch("src.bot.PersonaValidator", MagicMock()),
        patch("src.bot.PushPullEngine", MagicMock()),
        # note repo with engine.url that stringifies
        patch(
            "src.notes.repository.FanNoteRepository",
            return_value=_make_note_repo(),
        ),
    ]
    for p in patchers:
        p.start()

    # FanslyBot itself — so reload doesn't re-import the real class
    bot_patcher = patch("src.bot.FanslyBot")
    mock_bot_cls = bot_patcher.start()
    crm_patcher = patch("src.crm.sync.CrmSyncService")
    mock_crm_cls = crm_patcher.start()
    mock_crm = mock_crm_cls.return_value
    mock_crm.sync_cycle.return_value.had_activity = False
    mock_crm.sync_cycle.return_value.remaining_chats = 0
    mock_crm.sync_cycle.return_value.discovery_complete = True

    # client factory — replaces direct client construction in main.py
    factory_patcher = patch("src.client_factory.get_fansly_client")
    mock_get_client = factory_patcher.start()

    mock_client = MagicMock()
    mock_client.verify_auth.return_value = True
    mock_get_client.return_value = mock_client

    # Configure FanslyBot mock — default: stop after 1 call
    #
    # module_ref must resolve to the actual src.main module object, not
    # __import__("src.main") — for a dotted path with no fromlist, __import__
    # returns the top-level package (src), not the submodule. mod.running =
    # False would then set a stray attribute on the src package instead of
    # stopping the module's real while loop, turning the loop infinite.
    bot, _ = _make_controlled_bot(
        poll_side_effects=[None],
        module_ref=lambda: sys.modules["src.main"],
    )
    mock_bot_cls.return_value = bot

    all_patchers = patchers + [
        bot_patcher,
        crm_patcher,
        factory_patcher,
    ]

    yield {
        "client": mock_client,
        "client_cls": mock_get_client,
        "bot": bot,
        "bot_cls": mock_bot_cls,
        "crm_sync": mock_crm,
        "crm_sync_cls": mock_crm_cls,
    }

    for p in all_patchers:
        p.stop()


@pytest.fixture
def module(mock_deps):
    """Import src.main after low-level mocks are in place."""
    import src.main as mod
    return mod


# ═══════════════════════════════════════════════════════════════
# RED Phase — Tests for Startup Auth Validation
# ═══════════════════════════════════════════════════════════════

class TestStartupAuthValidation:
    """Startup auth check is non-fatal (commit de5dd57): on failure it logs a
    warning, disables the bot, and lets the dashboard keep running rather than
    sys.exit — so credential problems don't take down the whole process."""

    def test_auth_check_succeeds_does_not_exit(self, module, caplog, mock_deps):
        """On valid credentials, the startup check passes and no sys.exit."""
        importlib.reload(module)

        assert any(
            "API authentication verified" in r.message
            for r in caplog.records
        ), "Expected info log 'API authentication verified'"

    def test_controlled_launch_arguments_and_fail_closed_default(
        self,
        module,
        mock_deps,
    ):
        importlib.reload(module)

        kwargs = mock_deps["bot_cls"].call_args.kwargs
        assert kwargs["allowed_fan_ids"] == {"pilot-fan"}
        assert kwargs["require_fan_allowlist"] is True
        assert kwargs["max_proactive_per_hour"] == 0
        assert kwargs["max_proactive_per_day"] == 0
        assert kwargs["max_proactive_per_fan_per_day"] == 0
        assert kwargs["enable_stalled_outreach"] is False
        assert module.bot.enabled is False

    def test_crm_sync_runs_even_while_automated_replies_are_disabled(
        self,
        module,
        mock_deps,
    ):
        importlib.reload(module)

        assert module.bot.enabled is False
        mock_deps["crm_sync"].refresh_chat_index.assert_called()
        mock_deps["crm_sync"].sync_cycle.assert_called()

    def test_empty_pilot_allowlist_blocks_enabled_default(
        self,
        module,
        mock_deps,
    ):
        os.environ["BOT_ENABLED_DEFAULT"] = "true"
        os.environ["FAN_ALLOWLIST"] = ""
        mock_deps["bot"].launch_ready = False
        mock_deps["bot"].launch_block_reason = (
            "controlled launch requires at least one FAN_ALLOWLIST entry"
        )

        importlib.reload(module)

        assert module.bot.enabled is False

    def test_auth_check_warns_and_disables_bot_on_401(self, module, caplog, mock_deps):
        """AuthError logs a warning and disables the bot — no sys.exit."""
        mock_deps["client"].verify_auth.side_effect = AuthError("Invalid API key")

        importlib.reload(module)

        assert any(
            "API AUTH FAILED" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        ), "Expected WARNING log about API AUTH FAILED"
        assert module.bot is None

    def test_auth_check_warns_and_disables_bot_on_402(self, module, caplog, mock_deps):
        """PaymentRequiredError logs a warning and disables the bot — no sys.exit."""
        mock_deps["client"].verify_auth.side_effect = PaymentRequiredError("Billing needed")

        importlib.reload(module)

        assert any(
            "API PAYMENT REQUIRED" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        ), "Expected WARNING log about API PAYMENT REQUIRED"
        assert module.bot is None

    def test_auth_check_catches_other_errors_too(self, module, caplog, mock_deps):
        """Any other exception (e.g. NotFoundError) is also caught non-fatally —
        the auth check is deliberately a catch-all so startup never crashes on it."""
        mock_deps["client"].verify_auth.side_effect = NotFoundError("Not found")

        importlib.reload(module)

        assert any(
            "API check failed" in r.message and r.levelname == "WARNING"
            for r in caplog.records
        ), "Expected WARNING log about API check failed"
        assert module.bot is None

    def test_auth_check_failure_still_starts_poll_loop(self, module, caplog, mock_deps):
        """On auth failure, the dashboard/poll loop still starts (non-fatal) —
        it just runs with the bot disabled."""
        mock_deps["client"].verify_auth.side_effect = AuthError("Invalid API key")

        importlib.reload(module)

        assert any(
            "Dashboard-only mode active" in r.message
            for r in caplog.records
        ), "Dashboard-only mode should start when authentication fails"

    def test_missing_api_key_starts_dashboard_without_constructing_bot(
        self, module, caplog, mock_deps
    ):
        os.environ.pop("APIFANSLY_API_KEY", None)
        mock_deps["client"].verify_auth.reset_mock()
        mock_deps["bot_cls"].reset_mock()

        importlib.reload(module)

        mock_deps["client"].verify_auth.assert_not_called()
        mock_deps["bot_cls"].assert_not_called()
        assert module.bot is None
        assert any(
            "Dashboard-only mode active" in r.message
            for r in caplog.records
        )
        runtime = module.runtime_monitor.snapshot()
        assert runtime["last_poll_started_at"] is None
        assert runtime["last_poll_succeeded_at"] is None
        assert runtime["last_error"] == "ProviderBlocked"


# ═══════════════════════════════════════════════════════════════
# RED Phase — Tests for Exponential Backoff
# ═══════════════════════════════════════════════════════════════

class TestExponentialBackoff:
    """Main loop backoff must increase on failure, reset on success, cap at max."""

    def _run_loop(self, module, mock_deps, poll_side_effects, poll_interval="2",
                  max_backoff="60"):
        """Reload main with controlled bot, run until stoppage, return iterations."""
        os.environ["POLL_INTERVAL"] = poll_interval
        os.environ["MAX_BACKOFF"] = max_backoff

        bot, iter_idx = _make_controlled_bot(
            poll_side_effects=poll_side_effects,
            module_ref=lambda: module,
        )
        # Reassigning module.FanslyBot directly doesn't survive reload — reload
        # re-executes `from .bot import FanslyBot`, which rebinds it right back
        # to src.bot.FanslyBot (mock_deps["bot_cls"]). Configure that mock's
        # return_value instead, since it's patched at the source and persists.
        mock_deps["bot_cls"].return_value = bot

        importlib.reload(module)
        return iter_idx[0]

    def test_backoff_increases_after_consecutive_failures(self, module, mock_deps):
        """After 3 failures, backoff increases exponentially (2, 4, 8)."""
        failures = [Exception("err1"), Exception("err2"), Exception("err3")]
        iterations = self._run_loop(
            module, mock_deps, failures, poll_interval="2", max_backoff="60"
        )
        assert iterations >= 3, f"Expected ≥3 poll iterations, got {iterations}"

    def test_backoff_resets_on_success(self, module, mock_deps):
        """After success, backoff returns to POLL_INTERVAL."""
        results = [Exception("fail1"), Exception("fail2"),
                   None, Exception("fail3")]
        iterations = self._run_loop(
            module, mock_deps, results, poll_interval="2", max_backoff="60"
        )
        assert iterations >= 4, f"Expected ≥4 poll iterations, got {iterations}"

    def test_backoff_caps_at_max_backoff(self, module, mock_deps):
        """Backoff never exceeds MAX_BACKOFF=10."""
        many = [Exception(f"fail{i}") for i in range(10)]
        iterations = self._run_loop(
            module, mock_deps, many, poll_interval="5", max_backoff="10"
        )
        assert iterations >= 5, f"Expected ≥5 poll iterations, got {iterations}"

    @pytest.mark.parametrize(
        "api_error",
        [
            AuthError("Token expired"),
            PaymentRequiredError("Insufficient credits"),
        ],
    )
    def test_api_access_error_disables_bot_but_keeps_dashboard_alive(
        self, module, caplog, mock_deps, api_error
    ):
        """API access failures stop polling without terminating the web process."""
        os.environ["POLL_INTERVAL"] = "2"
        os.environ["MAX_BACKOFF"] = "8"

        bot, iter_idx = _make_controlled_bot(
            poll_side_effects=[None, api_error, None],
            module_ref=lambda: module,
        )
        mock_deps["bot_cls"].return_value = bot

        importlib.reload(module)

        assert iter_idx[0] >= 4, "The main process exited instead of keeping the dashboard alive"
        assert bot.enabled is False
        assert any(
            "Bot disabled" in r.message and "dashboard remains available" in r.message
            for r in caplog.records
        ), "Expected a non-fatal API access warning"


class TestIdleAdaptiveBackoff:
    """Poll interval backs off when idle (no unread), resets fast when active."""

    def _run_loop_idle(self, module, mock_deps, poll_return_values, poll_interval="2",
                        idle_backoff_max="60"):
        os.environ["POLL_INTERVAL"] = poll_interval
        os.environ["IDLE_BACKOFF_MAX"] = idle_backoff_max

        bot = MagicMock()
        bot.sequence_repo = MagicMock()
        iter_idx = [0]

        def _poll(*_args, **_kwargs):
            idx = iter_idx[0]
            iter_idx[0] += 1
            if idx >= len(poll_return_values):
                module.running = False
                return False
            return poll_return_values[idx]

        bot.poll_and_process = _poll
        # See TestExponentialBackoff._run_loop — module.FanslyBot doesn't
        # survive reload; configure the patched class's return_value instead.
        mock_deps["bot_cls"].return_value = bot

        importlib.reload(module)
        return iter_idx[0]

    def test_idle_cycles_increase_sleep_interval(self, module, mock_deps):
        """Three consecutive idle (False) cycles should still complete without error —
        interval grows but the loop keeps running."""
        iterations = self._run_loop_idle(
            module, mock_deps, [False, False, False], poll_interval="2", idle_backoff_max="60"
        )
        assert iterations >= 3

    def test_activity_resets_idle_backoff(self, module, mock_deps):
        """An active (True) cycle after idle ones resets the fast interval —
        loop should keep completing cycles without error."""
        iterations = self._run_loop_idle(
            module, mock_deps, [False, False, True, False], poll_interval="2", idle_backoff_max="60"
        )
        assert iterations >= 4


def test_crm_backfill_uses_dedicated_short_interval(
    module,
    mock_deps,
    caplog,
):
    os.environ["POLL_INTERVAL"] = "300"
    os.environ["CRM_SYNC_BACKFILL_INTERVAL"] = "30"
    result = mock_deps["crm_sync"].sync_cycle.return_value
    result.had_activity = True
    result.remaining_chats = 3
    result.discovery_complete = False

    importlib.reload(module)

    assert module.CRM_SYNC_BACKFILL_INTERVAL == 30
    assert any(
        "CRM history backfill pending; continuing in 30s" in record.message
        for record in caplog.records
    )


# ═══════════════════════════════════════════════════════════════
# RED Phase — Tests for Credit Awareness Logging
# ═══════════════════════════════════════════════════════════════

class TestCreditAwarenessLogging:
    """Provider-aware startup logging should not mix billing models."""

    def test_logs_estimated_monthly_requests(self, module, caplog):
        os.environ["POLL_INTERVAL"] = "300"
        importlib.reload(module)

        assert any(
            "8,640/month" in r.message
            and "APIFansly chat-list baseline" in r.message
            for r in caplog.records
        ), "Expected the APIFansly chat-list baseline in startup logs"

    def test_legacy_provider_warns_if_exceeding_basic_plan(self, module, caplog):
        os.environ["FANSLY_PROVIDER"] = "fanslyapi"
        os.environ["FANSLY_API_KEY"] = "legacy_test_key"
        os.environ["POLL_INTERVAL"] = "60"
        importlib.reload(module)

        assert any(
            "exceed the OnlyFansAPI Basic plan" in r.message
            for r in caplog.records
        ), "Expected warning about exceeding Basic plan credits"
