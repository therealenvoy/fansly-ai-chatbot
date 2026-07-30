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

from .service_role import ServiceRole
from .safe_logging import configure_privacy_safe_logging
from dotenv import load_dotenv

from .fansly_client import AuthError, PaymentRequiredError
from .client_factory import get_fansly_client
from .apifansly_client import ApifanslyClient, ApifanslyConfig
from .bulk_posting import BulkPostingService
from .fyp_analytics import FypAnalyticsService
from .provider_read_cache import ProviderReadCache
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
from .webhooks.registry import eligible_event_names
from .settings.store import SettingsStore
from .settings.ai import (
    AISettingsError,
    DeepSeekSettingsService,
    EncryptedCredentialStore,
)
from .settings.chat_guidance import ChatGuidanceService
from .settings.brain import BrainSettingsService
from .human_delivery.guide import DEFAULT_CONVERSATION_GUIDE
from .human_delivery.control import HumanDeliveryControlService
from .auto_messages.control import AutoMessagesControlService
from .human_delivery.service import HumanDeliveryService
from .persistence.database import create_database_engine
from .persistence.migrations import upgrade_database
from .persistence.state import ConversationStateRepository
from .operations import RuntimeMonitor
from .provider_credit import (
    ProviderBudgetExceeded,
    ProviderCircuitOpen,
    ProviderCreditGovernor,
    ProviderCreditSettings,
    provider_worker,
)
from .crm.sync import CrmSyncService
from .persistence.crm import CrmSyncRepository
from .conversation.llm import DeepSeekChatResponder
from .conversation.mode import BotMode
from .conversation.advanced import AdvancedBrainDecisionService
from .conversation.brain2 import BrainRuntimeSettings
from .conversation.brain2_episodes import ConversationEpisodeService
from .conversation.brain2_repository import ConversationEpisodeRepository
from .conversation.shadow import (
    DeepSeekStrategicAnalyzer,
    ShadowBrainService,
)

load_dotenv()

configure_privacy_safe_logging()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("fansly-bot")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# ─── Config ────────────────────────────────────────────

FANSLY_PROVIDER = os.getenv("FANSLY_PROVIDER", "apifansly").strip().lower()
SERVICE_ROLE = ServiceRole.parse(os.getenv("SERVICE_ROLE", "all"))
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
    21600,
    int(os.getenv("RECONCILIATION_INTERVAL", "21600")),
)
RECOVERY_RECONCILIATION_ENABLED = _env_bool(
    "RECOVERY_RECONCILIATION_ENABLED",
    False,
)
WEBHOOK_REGISTRATION_ENABLED = _env_bool(
    "WEBHOOK_REGISTRATION_ENABLED",
    False,
)
RECOVERY_CHAT_PAGES_PER_RUN = min(
    max(1, int(os.getenv("RECOVERY_CHAT_PAGES_PER_RUN", "2"))),
    10,
)
RECOVERY_MESSAGE_PAGES_PER_CHAT = min(
    max(
        1,
        int(
            os.getenv(
                "RECOVERY_MESSAGE_PAGES_PER_CHAT",
                "5",
            )
        ),
    ),
    10,
)
WEBHOOK_EVENT_PROFILE = os.getenv(
    "WEBHOOK_EVENT_PROFILE",
    "core_v1",
).strip()
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
CRM_SYNC_ENABLED = _env_bool("CRM_SYNC_ENABLED", False)
CRM_SYNC_INTERVAL = max(
    60,
    int(os.getenv("CRM_SYNC_INTERVAL", "300")),
)
CRM_SYNC_MESSAGE_PAGES_PER_CYCLE = min(
    max(
        int(os.getenv("CRM_SYNC_MESSAGE_PAGES_PER_CYCLE", "5")),
        1,
    ),
    100,
)
CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE = min(
    max(
        int(os.getenv("CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE", "1")),
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
PROVIDER_MONTHLY_CREDIT_LIMIT = max(
    0,
    int(os.getenv("PROVIDER_MONTHLY_CREDIT_LIMIT", "20000")),
)
PROVIDER_DAILY_READ_CREDIT_LIMIT = max(
    0,
    int(os.getenv("PROVIDER_DAILY_READ_CREDIT_LIMIT", "50")),
)
PROVIDER_MONTHLY_SEND_RESERVE = max(
    0,
    int(os.getenv("PROVIDER_MONTHLY_SEND_RESERVE", "15000")),
)
PROVIDER_MONTHLY_EMERGENCY_RESERVE = max(
    0,
    int(os.getenv("PROVIDER_MONTHLY_EMERGENCY_RESERVE", "2000")),
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
    logger.error(
        "Webhook configuration error: %s",
        type(error).__name__,
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
bulk_posting_client = None
if (
    os.getenv("APIFANSLY_API_KEY", "").strip()
    and os.getenv("FANSLY_ACCOUNT_ID", "").strip()
):
    bulk_posting_client = ApifanslyClient(
        ApifanslyConfig(
            api_key=os.getenv("APIFANSLY_API_KEY", "").strip(),
            account_id=os.getenv("FANSLY_ACCOUNT_ID", "").strip(),
        )
    )
bulk_posting = BulkPostingService(
    database_engine,
    creator_id=CREATOR_ID,
    client=bulk_posting_client,
)
fyp_analytics = FypAnalyticsService(
    client=bulk_posting_client,
    read_cache=ProviderReadCache(
        database_engine,
        creator_id=CREATOR_ID,
    ),
)
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
human_delivery_control = HumanDeliveryControlService(
    settings_store=settings_store,
    environment=os.environ,
)
human_delivery_settings = human_delivery_control.snapshot()
human_delivery = HumanDeliveryService(
    database_engine,
    creator_id=CREATOR_ID,
    settings=human_delivery_settings,
)
human_delivery_control.runtime = human_delivery
auto_messages_control = AutoMessagesControlService(
    settings_store=settings_store,
    environment=os.environ,
)
auto_messages_settings = auto_messages_control.snapshot()
try:
    guidance_snapshot = chat_guidance.snapshot()
    human_delivery.bootstrap(
        creator_persona=(
            persona_target.read_text(encoding="utf-8")
            if persona_target.exists()
            else ""
        ),
        brand_bible=guidance_snapshot.brand_bible,
        conversation_guide=guidance_snapshot.chat_instructions,
        suggested_guide=DEFAULT_CONVERSATION_GUIDE,
    )
except Exception as error:
    logger.warning(
        "Human Delivery document bootstrap failed safely: %s",
        type(error).__name__,
        exc_info=True,
    )
logger.info(
    "Human Delivery controls: %s",
    human_delivery_settings.safe_status(),
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
    logger.error(
        "DeepSeek credential configuration error: %s",
        type(error).__name__,
    )

# Long-term memory: persistent message history + LLM fact extraction
message_store = MessageStore(engine=database_engine)
fact_extractor = LLMFactExtractor(
    api_key=deepseek_api_key,
    model=ai_settings.model,
)
chat_responder = DeepSeekChatResponder(
    api_key=deepseek_api_key,
    model=ai_settings.model,
    max_output_tokens=int(os.getenv("BRAIN_MAX_OUTPUT_TOKENS", "800")),
    json_repair_attempts=int(os.getenv("BRAIN_JSON_REPAIR_ATTEMPTS", "1")),
)
brain_runtime_settings = BrainRuntimeSettings.from_mapping(os.environ)
strategic_analyzer = DeepSeekStrategicAnalyzer(
    api_key=deepseek_api_key,
    model=ai_settings.model,
    max_output_tokens=brain_runtime_settings.max_output_tokens,
)
shadow_brain_service = ShadowBrainService(
    engine=database_engine,
    creator_id=CREATOR_ID,
    settings=brain_runtime_settings,
    analyzer=strategic_analyzer,
)
brain_settings_service = BrainSettingsService(
    settings_store=settings_store,
    environment=os.environ,
    shadow_runtime=shadow_brain_service,
)
shadow_brain_service.update_settings(brain_settings_service.snapshot())
advanced_brain_service = AdvancedBrainDecisionService(
    engine=database_engine,
    creator_id=CREATOR_ID,
    analyzer=strategic_analyzer,
    settings_provider=brain_settings_service.snapshot,
)
episode_service = ConversationEpisodeService(
    creator_id=CREATOR_ID,
    message_store=message_store,
    repository=ConversationEpisodeRepository(database_engine),
)
ai_settings.fact_extractor = fact_extractor
ai_settings.chat_responder = chat_responder
ai_settings.strategic_analyzer = strategic_analyzer
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
provider_credit_governor = None
if FANSLY_PROVIDER == "fanslyapi":
    provider_credit_governor = ProviderCreditGovernor(
        database_engine,
        creator_id=CREATOR_ID,
        settings=ProviderCreditSettings(
            monthly_limit=PROVIDER_MONTHLY_CREDIT_LIMIT,
            daily_read_limit=PROVIDER_DAILY_READ_CREDIT_LIMIT,
            monthly_send_reserve=PROVIDER_MONTHLY_SEND_RESERVE,
            monthly_emergency_reserve=(
                PROVIDER_MONTHLY_EMERGENCY_RESERVE
            ),
        ),
    )
    attach_governor = getattr(client, "attach_credit_governor", None)
    if callable(attach_governor):
        attach_governor(provider_credit_governor)

# ─── Startup Auth Validation ───────────────────────────

api_ok = False
api_error = None
if API_KEY:
    try:
        client.verify_auth()
        logger.info("API authentication verified")
        api_ok = True
    except AuthError as e:
        api_error = type(e).__name__
        logger.warning(
            "API AUTH FAILED (%s). Dashboard will still work; bot will not poll.",
            type(e).__name__,
        )
    except PaymentRequiredError as e:
        api_error = type(e).__name__
        logger.warning(
            "API PAYMENT REQUIRED (%s). Bot will not poll until credits are added.",
            type(e).__name__,
        )
    except Exception as e:
        api_error = type(e).__name__
        logger.warning(
            "API check failed (%s). Bot will not poll.",
            type(e).__name__,
        )
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
                type(e).__name__,
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
            shadow_brain_service=shadow_brain_service,
            advanced_brain_service=advanced_brain_service,
            brain_settings_service=brain_settings_service,
            episode_service=episode_service,
            chat_guidance=chat_guidance,
            human_delivery=human_delivery,
            enable_unread_replies=ENABLE_UNREAD_REPLIES,
            enable_online_outreach=auto_messages_settings.online.enabled,
            enable_stalled_outreach=auto_messages_settings.stalled.enabled,
            outreach_existing_online=(
                auto_messages_settings.online.include_currently_online
            ),
            online_window_seconds=(
                auto_messages_settings.online.online_window_seconds
            ),
            proactive_cooldown_hours=(
                auto_messages_settings.online.cooldown_hours
            ),
            max_proactive_per_hour=(
                auto_messages_settings.online.max_per_hour
            ),
            max_proactive_per_day=(
                auto_messages_settings.online.max_per_day
            ),
            max_proactive_per_fan_per_day=(
                auto_messages_settings.online.max_per_fan_per_day
            ),
            presence_batch_size=PRESENCE_BATCH_SIZE,
            presence_poll_interval_seconds=(
                auto_messages_settings.online.poll_interval_seconds
            ),
            stalled_after_hours=(
                auto_messages_settings.stalled.stalled_after_hours
            ),
            stalled_scan_interval_seconds=(
                auto_messages_settings.stalled.scan_interval_seconds
            ),
            stalled_scan_batch_size=(
                auto_messages_settings.stalled.scan_batch_size
            ),
            reply_delay_min_seconds=REPLY_DELAY_MIN_SECONDS,
            reply_delay_max_seconds=REPLY_DELAY_MAX_SECONDS,
            processing_retry_base_seconds=(
                PROCESSING_RETRY_BASE_SECONDS
            ),
            processing_retry_max_seconds=(
                PROCESSING_RETRY_MAX_SECONDS
            ),
            recovery_chat_pages_per_run=(
                RECOVERY_CHAT_PAGES_PER_RUN
            ),
            recovery_message_pages_per_chat=(
                RECOVERY_MESSAGE_PAGES_PER_CHAT
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
        bot.update_auto_messages(auto_messages_settings)
        auto_messages_control.runtime = bot
        logger.info(f"Bot enabled state from DB: {bot.enabled}")
    except Exception as e:
        api_error = type(e).__name__
        logger.warning(
            "Bot initialization failed (%s). Dashboard will still work.",
            type(e).__name__,
            exc_info=True,
        )
        api_ok = False
        bot = None

if bot is None:
    settings_store.set("bot_enabled", "false")
    runtime_monitor.provider_blocked(api_error or "ProviderUnavailable")
    logger.info("Bot unavailable; starting dashboard-only mode")

# ─── Credit Awareness ──────────────────────────────────

logger.info(
    "Webhook-first provider mode: routine chat polling is disabled; "
    "recovery=%s interval=%ss chat_pages=%s message_pages=%s",
    RECOVERY_RECONCILIATION_ENABLED,
    RECONCILIATION_INTERVAL,
    RECOVERY_CHAT_PAGES_PER_RUN,
    RECOVERY_MESSAGE_PAGES_PER_CHAT,
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
    human_delivery=human_delivery,
    human_delivery_control=human_delivery_control,
    auto_messages_control=auto_messages_control,
    bulk_posting=bulk_posting,
    fyp_analytics=fyp_analytics,
    credit_governor=provider_credit_governor,
    onlyfansapi_webhook_secret=ONLYFANSAPI_WEBHOOK_SECRET,
    webhook_endpoint_url=ONLYFANSAPI_WEBHOOK_URL,
    webhook_registration_enabled=WEBHOOK_REGISTRATION_ENABLED,
    webhook_event_profile=WEBHOOK_EVENT_PROFILE,
    inbound_wakeup=reply_wakeup,
)


def run_server():
    logger.info(f"Dashboard on port {PORT} — visit / for control panel")
    while running:
        dashboard.handle_request()


server_thread = threading.Thread(target=run_server, daemon=True)
if SERVICE_ROLE.serves_api:
    server_thread.start()
else:
    logger.info("Dashboard/webhook server disabled for role %s", SERVICE_ROLE.value)

# ─── Poll Loop with Backoff ────────────────────────────

def _disable_bot_for_provider_error(error: Exception) -> None:
    if bot is not None:
        bot.enabled = False
    settings_store.set("bot_enabled", "false")
    runtime_monitor.provider_blocked(error)
    logger.warning(
        "API access unavailable: %s. Bot disabled; dashboard remains "
        "available.",
        type(error).__name__,
    )


def run_reply_worker(worker_number: int) -> None:
    """Drain durable inbound work without waiting for provider reconciliation."""
    consecutive_failures = 0
    while running and bot is not None:
        runtime_monitor.poll_started()
        try:
            with provider_worker(f"reply-worker-{worker_number}"):
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
        except (
            AuthError,
            PaymentRequiredError,
            ProviderBudgetExceeded,
            ProviderCircuitOpen,
        ) as error:
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
        if not bot.enabled:
            sleep_with_interrupt(RECONCILIATION_INTERVAL)
            continue
        try:
            with provider_worker("provider-reconciliation"):
                _, ingested = bot.reconcile_provider()
            if ingested:
                reply_wakeup.set()
        except (
            AuthError,
            PaymentRequiredError,
            ProviderBudgetExceeded,
            ProviderCircuitOpen,
        ) as error:
            _disable_bot_for_provider_error(error)
        except Exception:
            logger.exception("Provider reconciliation failed")
        sleep_with_interrupt(RECONCILIATION_INTERVAL)


def run_crm_worker() -> None:
    """Keep the CRM cache fresh independently from message delivery."""
    while running and crm_sync is not None:
        try:
            with provider_worker("crm-backfill"):
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
        except (
            AuthError,
            PaymentRequiredError,
            ProviderBudgetExceeded,
            ProviderCircuitOpen,
        ) as error:
            runtime_monitor.provider_blocked(error)
            logger.warning(
                "CRM provider-history sync paused: %s",
                type(error).__name__,
            )
            wait_seconds = CRM_SYNC_INTERVAL
        except Exception:
            logger.exception("CRM provider-history sync failed")
            wait_seconds = CRM_SYNC_INTERVAL
        sleep_with_interrupt(wait_seconds)


def run_outreach_worker() -> None:
    """Schedule proactive online and stalled work outside the reply path."""
    while running and bot is not None:
        if not bot.enabled:
            sleep_with_interrupt(5)
            continue
        try:
            with provider_worker("proactive-outreach"):
                had_activity = bool(bot.poll_presence_outreach())
                had_activity = bool(
                    bot.poll_stalled_outreach()
                ) or had_activity
            if had_activity:
                reply_wakeup.set()
        except (
            AuthError,
            PaymentRequiredError,
            ProviderBudgetExceeded,
            ProviderCircuitOpen,
        ) as error:
            _disable_bot_for_provider_error(error)
        except Exception:
            logger.exception("Proactive outreach scan failed")
        sleep_with_interrupt(5)


def run_bulk_posting_worker() -> None:
    """Submit the next bounded recurrence window for durable post rules."""
    while running:
        try:
            submitted = bulk_posting.run_due()
            if submitted:
                logger.info(
                    "Submitted %s recurring bulk-post rule(s)",
                    submitted,
                )
        except Exception:
            logger.exception("Bulk-post recurrence worker failed")
        sleep_with_interrupt(60)


def run_webhook_registration() -> None:
    """Register the signed Fansly message webhook without console access."""
    if (
        not WEBHOOK_REGISTRATION_ENABLED
        or FANSLY_PROVIDER != "fanslyapi"
        or not api_ok
    ):
        return
    if (
        provider_credit_governor is not None
        and provider_credit_governor.is_circuit_open()
    ):
        logger.warning(
            "Automatic webhook registration skipped: provider circuit is open"
        )
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
    ensure_webhook = getattr(client, "ensure_fansly_webhook", None)
    if not callable(ensure_webhook):
        logger.warning(
            "Automatic webhook registration is unavailable for this provider client"
        )
        return
    try:
        with provider_worker("webhook-registration"):
            webhook = ensure_webhook(
                ONLYFANSAPI_WEBHOOK_URL,
                ONLYFANSAPI_WEBHOOK_SECRET,
                eligible_event_names(WEBHOOK_EVENT_PROFILE),
            )
        logger.info(
            "OnlyFansAPI Fansly webhook active: id=%s profile=%s",
            webhook.get("id", "unknown"),
            WEBHOOK_EVENT_PROFILE,
        )
    except Exception:
        logger.exception(
            "Automatic OnlyFansAPI Fansly webhook registration failed; "
            "registration remains unreconciled and recovery policy is unchanged"
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
        "Starting Fansly Bot for creator '%s': role=%s, %s reply workers, %ss "
        "reconciliation",
        CREATOR_ID,
        SERVICE_ROLE.value,
        REPLY_WORKER_COUNT,
        RECONCILIATION_INTERVAL,
    )
    if SERVICE_ROLE.runs_scheduler and WEBHOOK_REGISTRATION_ENABLED:
        _start_background_worker(
            "webhook-registration",
            run_webhook_registration,
        )
    if SERVICE_ROLE.runs_scheduler and RECOVERY_RECONCILIATION_ENABLED:
        _start_background_worker(
            "provider-reconciliation",
            run_reconciliation_worker,
        )
    if (
        SERVICE_ROLE.runs_scheduler
        and (ENABLE_ONLINE_OUTREACH or ENABLE_STALLED_OUTREACH)
    ):
        _start_background_worker("proactive-outreach", run_outreach_worker)
    if SERVICE_ROLE.runs_reply_workers:
        for worker_index in range(2, REPLY_WORKER_COUNT + 1):
            _start_background_worker(
                f"reply-worker-{worker_index}",
                lambda index=worker_index: run_reply_worker(index),
            )

if crm_sync is not None and SERVICE_ROLE.runs_scheduler:
    _start_background_worker("crm-sync", run_crm_worker)

if bulk_posting.available and SERVICE_ROLE.runs_scheduler:
    _start_background_worker("bulk-posting", run_bulk_posting_worker)

if bot is not None and SERVICE_ROLE.runs_reply_workers:
    run_reply_worker(1)
else:
    while running:
        sleep_with_interrupt(IDLE_BACKOFF_MAX)

if bot is not None and bot.memory_extraction_service is not None:
    bot.memory_extraction_service.shutdown()
episode_service.shutdown()
if bulk_posting_client is not None:
    bulk_posting_client.close()
advanced_brain_service.shutdown()
shadow_brain_service.shutdown()
client.close()
logger.info("Bot stopped.")
