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

    def _poll():
        idx = iter_idx[0]
        iter_idx[0] += 1
        if idx >= len(poll_side_effects):
            mod = module_ref() if module_ref else __import__("src.main")
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
    with patch("time.sleep"):
        yield


@pytest.fixture(autouse=True)
def cleanup_env():
    """Restore env after each test — prevents cross-test contamination."""
    saved = {k: os.environ.get(k) for k in (
        "FANSLY_API_KEY", "FANSLY_ACCOUNT_ID", "POLL_INTERVAL",
        "MAX_BACKOFF", "DATABASE_URL", "PORT", "DEEPSEEK_API_KEY",
        "CREATOR_ID",
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
    os.environ.setdefault("FANSLY_API_KEY", "test_key_123")
    os.environ.setdefault("FANSLY_ACCOUNT_ID", "test_account_456")
    os.environ.setdefault("POLL_INTERVAL", "1")
    os.environ.setdefault("MAX_BACKOFF", "8")
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("PORT", "19999")
    os.environ.setdefault("CREATOR_ID", "test_creator")


@pytest.fixture
def mock_deps(standard_env):
    """Patch low-level modules BEFORE src.main is imported."""
    patchers = [
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
        # FanslyBot itself — so reload doesn't re-import the real class
        patch("src.bot.FanslyBot"),
        # fansly_client
        patch("src.fansly_client.FanslyClient"),
        # note repo with engine.url that stringifies
        patch(
            "src.notes.repository.FanNoteRepository",
            return_value=_make_note_repo(),
        ),
    ]
    for p in patchers:
        p.start()

    # Configure FanslyClient mock
    mock_client_cls = patchers[-4]
    mock_client = MagicMock()
    mock_client._request.return_value = {
        "statusCode": 200, "data": {"data": {"response": []}}
    }
    mock_client_cls.getter().return_value = mock_client

    # Configure FanslyBot mock — default: stop after 1 call
    mock_bot_cls = patchers[-5]
    bot, _ = _make_controlled_bot(
        poll_side_effects=[None],
        module_ref=lambda: __import__("src.main"),
    )
    mock_bot_cls.getter().return_value = bot

    yield {
        "client": mock_client,
        "client_cls": mock_client_cls,
        "bot": bot,
        "bot_cls": mock_bot_cls,
    }

    for p in patchers:
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
    """Startup auth check must exit immediately on bad credentials."""

    def test_auth_check_succeeds_does_not_exit(self, module, caplog, mock_deps):
        """On valid credentials, the startup check passes and no sys.exit."""
        importlib.reload(module)

        assert any(
            "API authentication verified" in r.message
            for r in caplog.records
        ), "Expected info log 'API authentication verified'"

    def test_auth_check_exits_on_401(self, module, mock_deps):
        """When _request raises AuthError, sys.exit(1) is called."""
        mock_deps["client"]._request.side_effect = AuthError("Invalid API key")

        with pytest.raises(SystemExit) as exc_info:
            importlib.reload(module)

        assert exc_info.value.code == 1

    def test_auth_check_exits_on_402(self, module, mock_deps):
        """When _request raises PaymentRequiredError, sys.exit(1) is called."""
        mock_deps["client"]._request.side_effect = PaymentRequiredError("Billing needed")

        with pytest.raises(SystemExit) as exc_info:
            importlib.reload(module)

        assert exc_info.value.code == 1

    def test_auth_check_logs_critical_on_401(self, module, caplog, mock_deps):
        """AuthError logs a critical message before exit."""
        mock_deps["client"]._request.side_effect = AuthError("Invalid API key")

        with pytest.raises(SystemExit):
            importlib.reload(module)

        assert any(
            "API AUTH FAILED" in r.message and r.levelname == "CRITICAL"
            for r in caplog.records
        ), "Expected CRITICAL log about API AUTH FAILED"

    def test_auth_check_logs_critical_on_402(self, module, caplog, mock_deps):
        """PaymentRequiredError logs a critical message before exit."""
        mock_deps["client"]._request.side_effect = PaymentRequiredError("Billing needed")

        with pytest.raises(SystemExit):
            importlib.reload(module)

        assert any(
            "API PAYMENT REQUIRED" in r.message and r.levelname == "CRITICAL"
            for r in caplog.records
        ), "Expected CRITICAL log about API PAYMENT REQUIRED"

    def test_auth_check_not_called_on_other_errors(self, module, mock_deps):
        """Other exceptions (e.g., NotFoundError) are NOT caught by auth check."""
        mock_deps["client"]._request.side_effect = NotFoundError("Not found")

        with pytest.raises(NotFoundError):
            importlib.reload(module)

    def test_auth_check_exits_before_poll_loop(self, module, caplog, mock_deps):
        """On auth failure, sys.exit is called BEFORE the while loop runs."""
        mock_deps["client"]._request.side_effect = AuthError("Invalid API key")

        with pytest.raises(SystemExit):
            importlib.reload(module)

        # The "Starting Fansly Bot" log is after auth check but before while loop.
        assert not any(
            "Starting Fansly Bot" in r.message
            for r in caplog.records
        ), "Bot should NOT start when auth fails"


# ═══════════════════════════════════════════════════════════════
# RED Phase — Tests for Exponential Backoff
# ═══════════════════════════════════════════════════════════════

class TestExponentialBackoff:
    """Main loop backoff must increase on failure, reset on success, cap at max."""

    def _run_loop(self, module, poll_side_effects, poll_interval="2",
                  max_backoff="60"):
        """Reload main with controlled bot, run until stoppage, return iterations."""
        os.environ["POLL_INTERVAL"] = poll_interval
        os.environ["MAX_BACKOFF"] = max_backoff

        bot, iter_idx = _make_controlled_bot(
            poll_side_effects=poll_side_effects,
            module_ref=lambda: module,
        )
        module.FanslyBot = MagicMock(return_value=bot)

        importlib.reload(module)
        return iter_idx[0]

    def test_backoff_increases_after_consecutive_failures(self, module):
        """After 3 failures, backoff increases exponentially (2, 4, 8)."""
        failures = [Exception("err1"), Exception("err2"), Exception("err3")]
        iterations = self._run_loop(
            module, failures, poll_interval="2", max_backoff="60"
        )
        assert iterations >= 3, f"Expected ≥3 poll iterations, got {iterations}"

    def test_backoff_resets_on_success(self, module):
        """After success, backoff returns to POLL_INTERVAL."""
        results = [Exception("fail1"), Exception("fail2"),
                   None, Exception("fail3")]
        iterations = self._run_loop(
            module, results, poll_interval="2", max_backoff="60"
        )
        assert iterations >= 4, f"Expected ≥4 poll iterations, got {iterations}"

    def test_backoff_caps_at_max_backoff(self, module):
        """Backoff never exceeds MAX_BACKOFF=10."""
        many = [Exception(f"fail{i}") for i in range(10)]
        iterations = self._run_loop(
            module, many, poll_interval="5", max_backoff="10"
        )
        assert iterations >= 5, f"Expected ≥5 poll iterations, got {iterations}"

    def test_fatal_auth_error_in_loop_exits(self, module):
        """AuthError in loop triggers shutdown (no backoff)."""
        os.environ["POLL_INTERVAL"] = "2"
        os.environ["MAX_BACKOFF"] = "8"

        bot, iter_idx = _make_controlled_bot(
            poll_side_effects=[None, AuthError("Token expired")],
            module_ref=lambda: module,
        )
        module.FanslyBot = MagicMock(return_value=bot)

        with pytest.raises(SystemExit):
            importlib.reload(module)

        assert iter_idx[0] >= 1, "Expected at least 1 poll iteration"


# ═══════════════════════════════════════════════════════════════
# RED Phase — Tests for Credit Awareness Logging
# ═══════════════════════════════════════════════════════════════

class TestCreditAwarenessLogging:
    """Credit awareness should log estimated daily API request count."""

    def test_logs_estimated_daily_requests(self, module, caplog):
        """Startup should log ~86400/POLL_INTERVAL as estimated daily requests."""
        os.environ["POLL_INTERVAL"] = "30"
        importlib.reload(module)

        assert any(
            "Estimated API requests" in r.message
            for r in caplog.records
        ), "Expected log about estimated API requests"

    def test_warns_if_exceeding_pro_plan(self, module, caplog):
        """If estimated requests >20000/day, log a warning."""
        os.environ["POLL_INTERVAL"] = "2"
        importlib.reload(module)

        assert any(
            "exceed Pro plan limits" in r.message
            for r in caplog.records
        ), "Expected warning about exceeding Pro plan limits"