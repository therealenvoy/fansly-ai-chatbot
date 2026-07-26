"""Main entry point for Fansly AI Chatbot.

Usage:
    python -m src.main

Requires:
    - FANSLY_PROVIDER=apifansly
    - APIFANSLY_API_KEY and FANSLY_ACCOUNT_ID
    - APIFANSLY_WEBHOOK_TOKEN for automatic PPV purchase handling
    - config/creators/{creator_id}.yaml persona file

Runs a polling bot loop + lightweight health check HTTP server on port 8080.
Performs startup auth validation and exponential backoff on failures.
"""

import os
import time
import logging
import signal
import shutil
import threading
from pathlib import Path

from dotenv import load_dotenv

from .fansly_client import AuthError, PaymentRequiredError
from .client_factory import get_fansly_client
from .persona.loader import PersonaLoader
from .notes.repository import FanNoteRepository
from .memory.store import MessageStore
from .memory.llm import LLMFactExtractor
from .bot import FanslyBot
from .web.dashboard import DashboardServer
from .settings.store import SettingsStore
from .persistence.database import create_database_engine
from .persistence.migrations import upgrade_database
from .persistence.state import ConversationStateRepository
from .operations import RuntimeMonitor
from .credit_budget import BASIC_MONTHLY_CREDITS, estimate_minimum_monthly_requests
from .crm.sync import CrmSyncService
from .persistence.crm import CrmSyncRepository

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fansly-bot")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# ─── Config ────────────────────────────────────────────

FANSLY_PROVIDER = os.getenv("FANSLY_PROVIDER", "apifansly").strip().lower()
API_KEY = (
    os.getenv("APIFANSLY_API_KEY", "")
    if FANSLY_PROVIDER == "apifansly"
    else os.getenv("FANSLY_API_KEY", "")
)
CREATOR_ID = os.getenv("CREATOR_ID", "sunny_charm")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))  # seconds, fast/active interval
IDLE_BACKOFF_MAX = int(os.getenv("IDLE_BACKOFF_MAX", "600"))  # cap for idle backoff
MAX_BACKOFF = int(os.getenv("MAX_BACKOFF", "600"))      # max seconds between polls on error
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/fansly_bot.db")
PORT = int(os.getenv("PORT", "8080"))
CONTROLLED_LAUNCH = _env_bool("CONTROLLED_LAUNCH", True)
BOT_ENABLED_DEFAULT = _env_bool("BOT_ENABLED_DEFAULT", False)
MAX_MESSAGES_PER_POLL = max(
    1,
    int(os.getenv("MAX_MESSAGES_PER_POLL", "5")),
)
CRM_SYNC_ENABLED = _env_bool("CRM_SYNC_ENABLED", True)
CRM_SYNC_MESSAGE_PAGES_PER_CYCLE = min(
    max(
        int(os.getenv("CRM_SYNC_MESSAGE_PAGES_PER_CYCLE", "25")),
        1,
    ),
    100,
)
CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE = min(
    max(
        int(os.getenv("CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE", "2")),
        1,
    ),
    10,
)
CRM_SYNC_BACKFILL_INTERVAL = max(
    1,
    min(
        int(os.getenv("CRM_SYNC_BACKFILL_INTERVAL", "30")),
        POLL_INTERVAL,
    ),
)
FAN_ALLOWLIST = {
    fan_id.strip()
    for fan_id in os.getenv("FAN_ALLOWLIST", "").split(",")
    if fan_id.strip()
}
PERSONA_CONFIG_DIR = os.getenv(
    "PERSONA_DIR",
    (
        "/data/config/creators"
        if os.getenv("RAILWAY_ENVIRONMENT_ID")
        else "config/creators"
    ),
)
BRAND_BIBLE_CONFIG_PATH = os.getenv(
    "BRAND_BIBLE_PATH",
    (
        "/data/config/brand_bible.md"
        if os.getenv("RAILWAY_ENVIRONMENT_ID")
        else "config/brand_bible.md"
    ),
)

if not API_KEY:
    logger.warning(
        f"The API key for provider '{FANSLY_PROVIDER}' is not configured. "
        "The dashboard will start, but polling remains disabled."
    )

# ─── Initialize ────────────────────────────────────────

database_engine = create_database_engine(DB_URL)
upgrade_database(DB_URL, engine=database_engine)
client = get_fansly_client(os.environ)
persona_target = Path(PERSONA_CONFIG_DIR) / f"{CREATOR_ID}.yaml"
persona_default = Path("config/creators") / f"{CREATOR_ID}.yaml"
if not persona_target.exists() and persona_default.exists():
    persona_target.parent.mkdir(parents=True, exist_ok=True)
    if persona_target.resolve() != persona_default.resolve():
        shutil.copyfile(persona_default, persona_target)
persona_loader = PersonaLoader(config_dir=PERSONA_CONFIG_DIR)
note_repo = FanNoteRepository(engine=database_engine)

# Long-term memory: persistent message history + LLM fact extraction
message_store = MessageStore(engine=database_engine)
fact_extractor = LLMFactExtractor(api_key=os.getenv("DEEPSEEK_API_KEY", ""))
if fact_extractor.enabled:
    logger.info("LLM fact extraction enabled (DeepSeek)")
else:
    logger.warning("DEEPSEEK_API_KEY not set — fact extraction disabled")

# Persistent bot settings (on/off toggle, etc.)
settings_store = SettingsStore(
    engine=database_engine,
    creator_id=CREATOR_ID,
)
state_repo = ConversationStateRepository(database_engine)
state_repo.ensure_creator(CREATOR_ID)
runtime_monitor = RuntimeMonitor()

# ─── Startup Auth Validation ───────────────────────────

api_ok = False
api_error = None
if API_KEY:
    try:
        client.verify_auth()
        logger.info("API authentication verified")
        api_ok = True
    except AuthError as e:
        api_error = str(e)
        logger.warning(f"API AUTH FAILED: {e}. Dashboard will still work, bot will not poll.")
    except PaymentRequiredError as e:
        api_error = str(e)
        logger.warning(f"API PAYMENT REQUIRED: {e}. Bot will not poll until credits added.")
    except Exception as e:
        api_error = str(e)
        logger.warning(f"API check failed: {e}. Bot will not poll.")
else:
    api_error = f"API key for provider '{FANSLY_PROVIDER}' is not configured"

bot = None
crm_sync = None
if api_ok:
    if CRM_SYNC_ENABLED:
        try:
            crm_sync = CrmSyncService(
                client=client,
                creator_id=CREATOR_ID,
                state_repo=state_repo,
                sync_repo=CrmSyncRepository(database_engine),
                message_store=message_store,
                message_page_budget=CRM_SYNC_MESSAGE_PAGES_PER_CYCLE,
                discovery_page_budget=(
                    CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE
                ),
            )
            logger.info(
                "CRM provider-history sync enabled: %s message pages and "
                "%s discovery pages per cycle; %ss backfill interval",
                CRM_SYNC_MESSAGE_PAGES_PER_CYCLE,
                CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE,
                CRM_SYNC_BACKFILL_INTERVAL,
            )
        except Exception as e:
            logger.warning(
                "CRM sync initialization failed: %s",
                e,
                exc_info=True,
            )
    try:
        bot = FanslyBot(
            client=client,
            persona_loader=persona_loader,
            note_repo=note_repo,
            creator_id=CREATOR_ID,
            message_store=message_store,
            fact_extractor=fact_extractor,
            state_repo=state_repo,
            allowed_fan_ids=FAN_ALLOWLIST,
            require_fan_allowlist=CONTROLLED_LAUNCH,
        )
        bot_enabled_str = settings_store.get(
            "bot_enabled",
            str(BOT_ENABLED_DEFAULT).lower(),
        )
        requested_enabled = str(bot_enabled_str).lower() == "true"
        if requested_enabled and not bool(bot.launch_ready):
            requested_enabled = False
            settings_store.set("bot_enabled", "false")
            logger.warning(
                "Persisted bot enable was blocked: %s",
                bot.launch_block_reason,
            )
        bot.enabled = requested_enabled
        logger.info(f"Bot enabled state from DB: {bot.enabled}")
    except Exception as e:
        api_error = str(e)
        logger.warning(f"Bot initialization failed: {e}. Dashboard will still work.", exc_info=True)
        api_ok = False
        bot = None

if bot is None:
    settings_store.set("bot_enabled", "false")
    runtime_monitor.provider_blocked(api_error or "ProviderUnavailable")
    logger.info("Bot unavailable; starting dashboard-only mode")

# ─── Credit Awareness ──────────────────────────────────

if FANSLY_PROVIDER == "fanslyapi":
    estimated_monthly = estimate_minimum_monthly_requests(POLL_INTERVAL)
    logger.info(
        "Estimated OnlyFansAPI request baseline (30 days, no idle "
        f"backoff): ~{estimated_monthly:,}/month at "
        f"{POLL_INTERVAL}s interval"
    )
    if estimated_monthly > BASIC_MONTHLY_CREDITS:
        logger.warning(
            f"At ~{estimated_monthly:,} baseline requests/month, this "
            f"configuration can exceed the OnlyFansAPI Basic plan "
            f"({BASIC_MONTHLY_CREDITS:,} credits/month)."
        )
else:
    estimated_chat_polls = (
        30 * 24 * 60 * 60 // max(POLL_INTERVAL, 1)
    )
    logger.info(
        "Estimated APIFansly chat-list baseline (30 days, no idle "
        f"backoff): ~{estimated_chat_polls:,}/month before message reads, "
        "vault reads, and sends"
    )

# ─── Main Loop ─────────────────────────────────────────

running = True


def sleep_with_interrupt(seconds: int):
    """Sleep with interrupt awareness — checks running flag every second."""
    for _ in range(seconds):
        if not running:
            break
        time.sleep(1)


def shutdown(signum, frame):
    global running
    logger.info("Shutting down...")
    running = False
    client.close()


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ─── Dashboard Server ──────────────────────────────────

dashboard = DashboardServer(
    bot,
    port=PORT,
    engine=database_engine,
    client=client,
    creator_id=CREATOR_ID,
    provider_connected=api_ok,
    provider_error=api_error,
    persona_dir=PERSONA_CONFIG_DIR,
    brand_bible_path=BRAND_BIBLE_CONFIG_PATH,
    runtime_monitor=runtime_monitor,
)


def run_server():
    logger.info(f"Dashboard on port {PORT} — visit / for control panel")
    while running:
        dashboard.handle_request()


server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

# ─── Poll Loop with Backoff ────────────────────────────

if bot is None:
    logger.info("Dashboard-only mode active; Fansly polling is disabled")
else:
    logger.info(f"Starting Fansly Bot for creator '{CREATOR_ID}'")
    logger.info(
        "Provider: %s, account: %s, poll interval: %ss",
        FANSLY_PROVIDER,
        client.account_id,
        POLL_INTERVAL,
    )
logger.info(f"Max failure backoff: {MAX_BACKOFF}s, max idle backoff: {IDLE_BACKOFF_MAX}s")

consecutive_failures = 0
consecutive_idle_cycles = 0

while running:
    if bot is None and crm_sync is None:
        sleep_with_interrupt(IDLE_BACKOFF_MAX)
        continue

    had_activity = False
    crm_backfill_pending = False
    runtime_monitor.poll_started()
    try:
        if crm_sync is not None:
            crm_result = crm_sync.sync_cycle()
            had_activity = bool(crm_result.had_activity)
            crm_backfill_pending = bool(
                crm_result.remaining_chats > 0
                or not crm_result.discovery_complete
            )
        if bot is not None:
            had_activity = bool(
                bot.poll_and_process(
                    max_chats=MAX_MESSAGES_PER_POLL
                )
            ) or had_activity
        consecutive_failures = 0  # reset on success
        runtime_monitor.poll_succeeded(had_activity=bool(had_activity))
    except (AuthError, PaymentRequiredError) as e:
        if bot is not None:
            bot.enabled = False
        settings_store.set("bot_enabled", "false")
        consecutive_failures = 0
        runtime_monitor.provider_blocked(e)
        logger.warning(
            f"API access unavailable: {e}. "
            "Bot disabled; dashboard remains available."
        )
    except Exception as e:
        consecutive_failures += 1
        runtime_monitor.poll_failed(e)
        logger.error(f"Error in main loop ({consecutive_failures} consecutive): {e}", exc_info=True)

    # Failure backoff takes priority over idle backoff for this cycle.
    if consecutive_failures > 0:
        consecutive_idle_cycles = 0
        backoff = min(POLL_INTERVAL * (2 ** (consecutive_failures - 1)), MAX_BACKOFF)
        logger.warning(f"Backoff: sleeping {backoff}s (failure #{consecutive_failures})")
    elif crm_backfill_pending:
        consecutive_idle_cycles = 0
        backoff = CRM_SYNC_BACKFILL_INTERVAL
        logger.info(
            "CRM history backfill pending; continuing in %ss",
            backoff,
        )
    elif had_activity:
        consecutive_idle_cycles = 0
        backoff = POLL_INTERVAL
    else:
        consecutive_idle_cycles += 1
        backoff = min(POLL_INTERVAL * (2 ** consecutive_idle_cycles), IDLE_BACKOFF_MAX)
        logger.debug(f"Idle: sleeping {backoff}s (idle cycle #{consecutive_idle_cycles})")

    sleep_with_interrupt(backoff)

logger.info("Bot stopped.")
