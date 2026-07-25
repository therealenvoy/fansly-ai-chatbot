"""Main entry point for Fansly AI Chatbot.

Usage:
    python -m src.main

Requires:
    - FANSLY_API_KEY env var (your apifansly.com API key)
    - FANSLY_ACCOUNT_ID env var (your connected account ID)
    - config/creators/{creator_id}.yaml persona file

Runs a polling bot loop + lightweight health check HTTP server on port 8080.
Performs startup auth validation and exponential backoff on failures.
"""

import os
import sys
import time
import logging
import signal
import threading

from dotenv import load_dotenv

from .fansly_client import FanslyClient, FanslyConfig, AuthError, PaymentRequiredError
from .persona.loader import PersonaLoader
from .notes.repository import FanNoteRepository
from .memory.store import MessageStore
from .memory.llm import LLMFactExtractor
from .bot import FanslyBot
from .web.dashboard import DashboardServer
from .settings.store import SettingsStore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fansly-bot")

# ─── Config ────────────────────────────────────────────

API_KEY = os.getenv("FANSLY_API_KEY", "") or os.getenv("APIFANSLY_API_KEY", "")
ACCOUNT_ID = os.getenv("FANSLY_ACCOUNT_ID", "")
CREATOR_ID = os.getenv("CREATOR_ID", "sunny_charm")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # seconds
MAX_BACKOFF = int(os.getenv("MAX_BACKOFF", "600"))      # max seconds between polls
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/fansly_bot.db")
PORT = int(os.getenv("PORT", "8080"))

if not API_KEY or not ACCOUNT_ID:
    logger.error("Missing FANSLY_API_KEY or FANSLY_ACCOUNT_ID. Set as env vars.")
    sys.exit(1)

# ─── Initialize ────────────────────────────────────────

config = FanslyConfig(api_key=API_KEY, account_id=ACCOUNT_ID)
client = FanslyClient(config)
persona_loader = PersonaLoader(config_dir="config/creators")
note_repo = FanNoteRepository(db_url=DB_URL)
note_repo.create_table()

# Long-term memory: persistent message history + LLM fact extraction
message_store = MessageStore(db_url=DB_URL)
message_store.create_table()
fact_extractor = LLMFactExtractor(api_key=os.getenv("DEEPSEEK_API_KEY", ""))
if fact_extractor.enabled:
    logger.info("LLM fact extraction enabled (DeepSeek)")
else:
    logger.warning("DEEPSEEK_API_KEY not set — fact extraction disabled")

# Persistent bot settings (on/off toggle, etc.)
settings_store = SettingsStore(db_url=DB_URL)
settings_store.create_table()

bot = FanslyBot(
    client=client,
    persona_loader=persona_loader,
    note_repo=note_repo,
    creator_id=CREATOR_ID,
    message_store=message_store,
    fact_extractor=fact_extractor,
)

# Initialize PPV sequence system
bot.sequence_repo.create_tables()

# Initialize bot enabled state from persistent settings
bot_enabled_str = settings_store.get("bot_enabled", "true")
bot.enabled = bot_enabled_str.lower() == "true"
logger.info(f"Bot enabled state from DB: {bot.enabled}")

# ─── Startup Auth Validation ───────────────────────────

try:
    # Minimal API call to verify credentials before entering poll loop
    client._request("GET", f"/{ACCOUNT_ID}/chats", params={"limit": 1})
    logger.info("API authentication verified")
    api_ok = True
except AuthError as e:
    logger.warning(f"API AUTH FAILED: {e}. Dashboard will still work, bot will not poll.")
    api_ok = False
except PaymentRequiredError as e:
    logger.warning(f"API PAYMENT REQUIRED: {e}. Bot will not poll until credits added.")
    api_ok = False
except Exception as e:
    logger.warning(f"API check failed: {e}. Bot will not poll.")
    api_ok = False

# If API is down, disable bot by default
if not api_ok:
    bot.enabled = False
    settings_store.set("bot_enabled", "false")
    logger.info("Bot auto-disabled due to API unavailability — toggle on from dashboard when ready")

# ─── Credit Awareness ──────────────────────────────────

estimated_daily = 86400 // POLL_INTERVAL
logger.info(f"Estimated API requests: ~{estimated_daily}/day at {POLL_INTERVAL}s interval")
if estimated_daily > 20000:
    logger.warning(
        f"At ~{estimated_daily} requests/day, you may exceed Pro plan limits (24K credits/mo). "
        f"Consider increasing POLL_INTERVAL."
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

dashboard = DashboardServer(bot, port=PORT)


def run_server():
    logger.info(f"Dashboard on port {PORT} — visit / for control panel")
    while running:
        dashboard.handle_request()


server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

# ─── Poll Loop with Backoff ────────────────────────────

logger.info(f"Starting Fansly Bot for creator '{CREATOR_ID}'")
logger.info(f"Account: {ACCOUNT_ID}, Poll interval: {POLL_INTERVAL}s")
logger.info(f"Max backoff: {MAX_BACKOFF}s")

consecutive_failures = 0

while running:
    try:
        bot.poll_and_process()
        consecutive_failures = 0  # reset on success
    except (AuthError, PaymentRequiredError) as e:
        logger.critical(f"Fatal API error: {e}. Shutting down.")
        running = False
        break
    except Exception as e:
        consecutive_failures += 1
        logger.error(f"Error in main loop ({consecutive_failures} consecutive): {e}", exc_info=True)

    # Calculate backoff
    if consecutive_failures > 0:
        backoff = min(POLL_INTERVAL * (2 ** (consecutive_failures - 1)), MAX_BACKOFF)
        logger.warning(f"Backoff: sleeping {backoff}s (failure #{consecutive_failures})")
    else:
        backoff = POLL_INTERVAL

    sleep_with_interrupt(backoff)

logger.info("Bot stopped.")