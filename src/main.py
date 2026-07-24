"""
Main entry point for Fansly AI Chatbot.

Usage:
    python -m src.main

Requires:
    - FANSLY_API_KEY env var (your apifansly.com API key)
    - FANSLY_ACCOUNT_ID env var (your connected account ID)
    - config/creators/{creator_id}.yaml persona file
"""

import os
import sys
import time
import logging
import signal

from dotenv import load_dotenv

from .fansly_client import FanslyClient, FanslyConfig
from .persona.loader import PersonaLoader
from .notes.repository import FanNoteRepository
from .bot import FanslyBot

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fansly-bot")

# ─── Config ────────────────────────────────────────────

API_KEY = os.getenv("FANSLY_API_KEY", "")
ACCOUNT_ID = os.getenv("FANSLY_ACCOUNT_ID", "")
CREATOR_ID = os.getenv("CREATOR_ID", "sunny_charm")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # seconds
DB_URL = os.getenv("DATABASE_URL", "sqlite:///data/fansly_bot.db")

if not API_KEY or not ACCOUNT_ID:
    logger.error("Missing FANSLY_API_KEY or FANSLY_ACCOUNT_ID. Set in .env file.")
    sys.exit(1)

# ─── Initialize ────────────────────────────────────────

config = FanslyConfig(api_key=API_KEY, account_id=ACCOUNT_ID)
client = FanslyClient(config)
persona_loader = PersonaLoader(config_dir="config/creators")
note_repo = FanNoteRepository(db_url=DB_URL)
note_repo.create_table()

bot = FanslyBot(
    client=client,
    persona_loader=persona_loader,
    note_repo=note_repo,
    creator_id=CREATOR_ID,
)

running = True


def shutdown(signum, frame):
    global running
    logger.info("Shutting down...")
    running = False
    client.close()


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ─── Main Loop ─────────────────────────────────────────

logger.info(f"Starting Fansly Bot for creator '{CREATOR_ID}'")
logger.info(f"Account: {ACCOUNT_ID}, Poll interval: {POLL_INTERVAL}s")

while running:
    try:
        bot.poll_and_process()
    except Exception as e:
        logger.error(f"Error in main loop: {e}", exc_info=True)

    # Sleep with interrupt awareness
    for _ in range(POLL_INTERVAL):
        if not running:
            break
        time.sleep(1)

logger.info("Bot stopped.")
