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
from .webhooks.registration import (
    production_webhook_url,
    resolve_signing_secret,
)
from .settings.store import SettingsStore
from .settings.ai import (
    AISettingsError,
    DeepSeekSettingsService,
    EncryptedCredentialStore,
)
from .settings.chat_guidance import ChatGuidanceService
from .persistence.database import create_database_engine
from .persistence.migrations import upgrade_database
from .persistence.state import ConversationStateRepository
from .operations import RuntimeMonitor
from .credit_budget import BASIC_MONTHLY_CREDITS, estimate_minimum_monthly_requests
from .crm.sync import CrmSyncService
from .persistence.crm import CrmSyncRepository
from .conversation.llm import DeepSeekChatResponder
from .conversation.mode import BotMode

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
BOT_MODE = BotMode.parse(os.getenv("BOT_MODE", "full_ppv"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))  # seconds, fast/active interval
IDLE_BACKOFF_MAX = int(os.getenv("IDLE_BACKOFF_MAX", "600"))  # cap for idle backoff
MAX_BACKOFF = int(os.getenv("MAX_BACKOFF", "600"))      # max seconds between polls on error
REPLY_WORKER_COUNT = min(
    max(1, int(os.getenv("REPLY_WORKER_COUNT", "2"))),
    4,
)
REPLY_WORKER_IDLE_SECONDS = max(
    1,
    int(os.getenv("REPLY_WORKER_IDLE_SECONDS", "1")),
)
RECONCILIATION_INTERVAL = max(
    60,
    int(os.getenv("RECONCILIATION_INTERVAL", str(POLL_INTERVAL))),
)
REPLY_DELAY_MIN_SECONDS = max(
    0,
    int(os.getenv("REPLY_DELAY_MIN_SECONDS", "5")),
)
REPLY_DELAY_MAX_SECONDS = max(
    REPLY_DELAY_MIN_SECONDS,
    int(os.getenv("REPLY_DELAY_MAX_SECONDS", "25")),
)
PROCESSING_RETRY_BASE_SECONDS = max(
    1,
    int(os.getenv("PROCESSING_RETRY_BASE_SECONDS", "5")),
)
PROCESSING_RETRY_MAX_SECONDS = max(
    PROCESSING_RETRY_BASE_SECONDS,
    int(os.getenv("PROCESSING_RETRY_MAX_SECONDS", "60")),
)
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/fansly_bot.db")
PORT = int(os.getenv("PORT", "8080"))
CONTROLLED_LAUNCH = _env_bool("CONTROLLED_LAUNCH", True)
BOT_ENABLED_DEFAULT = _env_bool("BOT_ENABLED_DEFAULT", False)
MAX_MESSAGES_PER_POLL = max(
    1,
    int(os.getenv("MAX_MESSAGES_PER_POLL", "5")),
)
ENABLE_UNREAD_REPLIES = _env_bool("ENABLE_UNREAD_REPLIES", True)
ENABLE_ONLINE_OUTREACH = _env_bool("ENABLE_ONLINE_OUTREACH", False)
ENABLE_STALLED_OUTREACH = _env_bool(
    "ENABLE_STALLED_OUTREACH",
    False,
)
OUTREACH_EXISTING_ONLINE = _env_bool(
    "OUTREACH_EXISTING_ONLINE",
    False,
)
ONLINE_WINDOW_SECONDS = max(
    60,
    int(os.getenv("ONLINE_WINDOW_SECONDS", "600")),
)
PROACTIVE_COOLDOWN_HOURS = max(
    1,
    int(os.getenv("PROACTIVE_COOLDOWN_HOURS", "48")),
)
MAX_PROACTIVE_PER_HOUR = max(
    0,
    int(os.getenv("MAX_PROACTIVE_PER_HOUR", "0")),
)
MAX_PROACTIVE_PER_DAY = max(
    0,
    int(os.getenv("MAX_PROACTIVE_PER_DAY", "0")),
)
MAX_PROACTIVE_PER_FAN_PER_DAY = max(
    0,
    int(os.getenv("MAX_PROACTIVE_PER_FAN_PER_DAY", "0")),
)
PRESENCE_BATCH_SIZE = min(
    max(1, int(os.getenv("PRESENCE_BATCH_SIZE", "100"))),
    100,
)
PRESENCE_POLL_INTERVAL = max(
    60,
    int(os.getenv("PRESENCE_POLL_INTERVAL", "300")),
)
STALLED_AFTER_HOURS = max(
    1,
    int(os.getenv("STALLED_AFTER_HOURS", "24")),
)
STALLED_SCAN_INTERVAL = max(
    60,
    int(os.getenv("STALLED_SCAN_INTERVAL", "300")),
)
STALLED_SCAN_BATCH_SIZE = min(
    max(1, int(os.getenv("STALLED_SCAN_BATCH_SIZE", "5000"))),
    5000,
)
CRM_SYNC_ENABLED = _env_bool("CRM_SYNC_ENABLED", True)
CRM_SYNC_INTERVAL = max(
    60,
    int(os.getenv("CRM_SYNC_INTERVAL", "300")),
)
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

try:
    ONLYFANSAPI_WEBHOOK_SECRET = resolve_signing_secret(os.environ)
    ONLYFANSAPI_WEBHOOK_URL = production_webhook_url(os.environ)
except ValueError as error:
    ONLYFANSAPI_WEBHOOK_SECRET = ""
    ONLYFANSAPI_WEBHOOK_URL = ""
    logger.error("Webhook configuration error: %s", error)

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

# Persistent bot settings (on/off toggle, etc.)
settings_store = SettingsStore(
    engine=database_engine,
    creator_id=CREATOR_ID,
)
chat_guidance = ChatGuidanceService(
    settings_store,
    legacy_brand_bible_path=BRAND_BIBLE_CONFIG_PATH,
)
credential_store = EncryptedCredentialStore(
    settings_store,
    os.getenv("CREDENTIAL_ENCRYPTION_KEY", ""),
)
ai_settings = DeepSeekSettingsService(
    settings_store=settings_store,
    credential_store=credential_store,
    environment_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    environment_model=os.getenv("DEEPSEEK_MODEL", ""),
)
try:
    deepseek_api_key, deepseek_key_source = ai_settings.active_api_key()
except AISettingsError as error:
    deepseek_api_key = ""
    deepseek_key_source = "configuration_error"
    logger.error("DeepSeek credential configuration error: %s", error)

# Long-term memory: persistent message history + LLM fact extraction
message_store = MessageStore(engine=database_engine)
fact_extractor = LLMFactExtractor(
    api_key=deepseek_api_key,
    model=ai_settings.model,
)
chat_responder = DeepSeekChatResponder(
    api_key=deepseek_api_key,
    model=ai_settings.model,
)
ai_settings.fact_extractor = fact_extractor
ai_settings.chat_responder = chat_responder
if fact_extractor.enabled:
    logger.info(
        "DeepSeek enabled: model=%s source=%s",
        ai_settings.model,
        deepseek_key_source,
    )
else:
    logger.warning(
        "DeepSeek is not configured — fact extraction and conversation "
        "generation are disabled"
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
            bot_mode=BOT_MODE,
            chat_responder=chat_responder,
            chat_guidance=chat_guidance,
            enable_unread_replies=ENABLE_UNREAD_REPLIES,
            enable_online_outreach=ENABLE_ONLINE_OUTREACH,
            enable_stalled_outreach=ENABLE_STALLED_OUTREACH,
            outreach_existing_online=OUTREACH_EXISTING_ONLINE,
            online_window_seconds=ONLINE_WINDOW_SECONDS,
            proactive_cooldown_hours=PROACTIVE_COOLDOWN_HOURS,
            max_proactive_per_hour=MAX_PROACTIVE_PER_HOUR,
            max_proactive_per_day=MAX_PROACTIVE_PER_DAY,
            max_proactive_per_fan_per_day=(
                MAX_PROACTIVE_PER_FAN_PER_DAY
            ),
            presence_batch_size=PRESENCE_BATCH_SIZE,
            presence_poll_interval_seconds=PRESENCE_POLL_INTERVAL,
            stalled_after_hours=STALLED_AFTER_HOURS,
            stalled_scan_interval_seconds=STALLED_SCAN_INTERVAL,
            stalled_scan_batch_size=STALLED_SCAN_BATCH_SIZE,
            reply_delay_min_seconds=REPLY_DELAY_MIN_SECONDS,
            reply_delay_max_seconds=REPLY_DELAY_MAX_SECONDS,
            processing_retry_base_seconds=(
                PROCESSING_RETRY_BASE_SECONDS
            ),
            processing_retry_max_seconds=(
                PROCESSING_RETRY_MAX_SECONDS
            ),
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
reply_wakeup = threading.Event()
background_threads: list[threading.Thread] = []


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
    reply_wakeup.set()


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
    crm_sync=crm_sync,
    ai_settings=ai_settings,
    chat_guidance=chat_guidance,
    onlyfansapi_webhook_secret=ONLYFANSAPI_WEBHOOK_SECRET,
    inbound_wakeup=reply_wakeup,
)


def run_server():
    logger.info(f"Dashboard on port {PORT} — visit / for control panel")
    while running:
        dashboard.handle_request()


server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

# ─── Poll Loop with Backoff ────────────────────────────

def _disable_bot_for_provider_error(error: Exception) -> None:
    if bot is not None:
        bot.enabled = False
    settings_store.set("bot_enabled", "false")
    runtime_monitor.provider_blocked(error)
    logger.warning(
        "API access unavailable: %s. Bot disabled; dashboard remains "
        "available.",
        error,
    )


def run_reply_worker(worker_number: int) -> None:
    """Drain durable inbound work without waiting for provider reconciliation."""
    consecutive_failures = 0
    while running and bot is not None:
        runtime_monitor.poll_started()
        try:
            had_activity = bool(
                bot.poll_and_process(
                    max_chats=MAX_MESSAGES_PER_POLL,
                    reconcile=False,
                    outreach=False,
                )
            )
            consecutive_failures = 0
            runtime_monitor.poll_succeeded(had_activity=had_activity)
            wait_seconds = (
                0 if had_activity else REPLY_WORKER_IDLE_SECONDS
            )
        except (AuthError, PaymentRequiredError) as error:
            consecutive_failures = 0
            _disable_bot_for_provider_error(error)
            wait_seconds = REPLY_WORKER_IDLE_SECONDS
        except Exception as error:
            consecutive_failures += 1
            runtime_monitor.poll_failed(error)
            wait_seconds = min(
                REPLY_WORKER_IDLE_SECONDS
                * (2 ** (consecutive_failures - 1)),
                MAX_BACKOFF,
            )
            logger.error(
                "Reply worker %s failed (%s consecutive); retrying in %ss",
                worker_number,
                consecutive_failures,
                wait_seconds,
                exc_info=True,
            )

        if wait_seconds > 0 and running:
            reply_wakeup.clear()
            for _ in range(wait_seconds):
                if not running or reply_wakeup.is_set():
                    break
                time.sleep(1)


def run_reconciliation_worker() -> None:
    """Recover missed events using a bounded provider poll."""
    while running and bot is not None:
        try:
            _, ingested = bot.reconcile_provider()
            if ingested:
                reply_wakeup.set()
        except (AuthError, PaymentRequiredError) as error:
            _disable_bot_for_provider_error(error)
        except Exception:
            logger.exception("Provider reconciliation failed")
        sleep_with_interrupt(RECONCILIATION_INTERVAL)


def run_crm_worker() -> None:
    """Keep the CRM cache fresh independently from message delivery."""
    first_cycle = True
    while running and crm_sync is not None:
        try:
            if first_cycle:
                crm_sync.refresh_chat_index()
                first_cycle = False
            result = crm_sync.sync_cycle()
            backfill_pending = bool(
                result.remaining_chats > 0
                or not result.discovery_complete
            )
            wait_seconds = (
                CRM_SYNC_BACKFILL_INTERVAL
                if backfill_pending
                else CRM_SYNC_INTERVAL
            )
            if backfill_pending:
                logger.info(
                    "CRM history backfill pending; continuing in %ss",
                    wait_seconds,
                )
        except Exception:
            logger.exception("CRM provider-history sync failed")
            wait_seconds = CRM_SYNC_INTERVAL
        sleep_with_interrupt(wait_seconds)


def run_outreach_worker() -> None:
    """Schedule proactive online and stalled work outside the reply path."""
    while running and bot is not None:
        try:
            had_activity = bool(bot.poll_presence_outreach())
            had_activity = bool(
                bot.poll_stalled_outreach()
            ) or had_activity
            if had_activity:
                reply_wakeup.set()
        except (AuthError, PaymentRequiredError) as error:
            _disable_bot_for_provider_error(error)
        except Exception:
            logger.exception("Proactive outreach scan failed")
        sleep_with_interrupt(5)


def run_webhook_registration() -> None:
    """Register the signed Fansly message webhook without console access."""
    if FANSLY_PROVIDER != "fanslyapi" or not api_ok:
        return
    if not ONLYFANSAPI_WEBHOOK_URL:
        logger.warning(
            "Automatic webhook registration skipped: RAILWAY_PUBLIC_DOMAIN is missing"
        )
        return
    if not ONLYFANSAPI_WEBHOOK_SECRET:
        logger.warning(
            "Automatic webhook registration skipped: no strong signing-secret source"
        )
        return
    ensure_webhook = getattr(client, "ensure_message_webhook", None)
    if not callable(ensure_webhook):
        logger.warning(
            "Automatic webhook registration is unavailable for this provider client"
        )
        return
    try:
        webhook = ensure_webhook(
            ONLYFANSAPI_WEBHOOK_URL,
            ONLYFANSAPI_WEBHOOK_SECRET,
        )
        logger.info(
            "OnlyFansAPI Fansly webhook active: id=%s event=%s",
            webhook.get("id", "unknown"),
            "fansly.messages.received",
        )
    except Exception:
        logger.exception(
            "Automatic OnlyFansAPI Fansly webhook registration failed; "
            "polling reconciliation remains active"
        )


def _start_background_worker(name: str, target) -> None:
    thread = threading.Thread(
        target=target,
        name=name,
        daemon=True,
    )
    background_threads.append(thread)
    thread.start()


if bot is None:
    logger.info("Dashboard-only mode active; Fansly polling is disabled")
else:
    logger.info(
        "Starting Fansly Bot for creator '%s': %s reply workers, %ss "
        "reconciliation",
        CREATOR_ID,
        REPLY_WORKER_COUNT,
        RECONCILIATION_INTERVAL,
    )
    _start_background_worker(
        "webhook-registration",
        run_webhook_registration,
    )
    _start_background_worker(
        "provider-reconciliation",
        run_reconciliation_worker,
    )
    _start_background_worker("proactive-outreach", run_outreach_worker)
    for worker_index in range(2, REPLY_WORKER_COUNT + 1):
        _start_background_worker(
            f"reply-worker-{worker_index}",
            lambda index=worker_index: run_reply_worker(index),
        )

if crm_sync is not None:
    _start_background_worker("crm-sync", run_crm_worker)

if bot is not None:
    run_reply_worker(1)
else:
    while running:
        sleep_with_interrupt(IDLE_BACKOFF_MAX)

client.close()
logger.info("Bot stopped.")
