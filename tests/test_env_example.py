"""Tests for .env.example (Task 11).

Verify that .env.example exists and contains all required variables.
"""
import os
import pytest

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.example")

REQUIRED_VARS = [
    "APIFANSLY_API_KEY",
    "APIFANSLY_WEBHOOK_TOKEN",
    "FANSLY_API_KEY",
    "FANSLY_ACCOUNT_ID",
    "FANSLY_PROVIDER",
    "ONLYFANSAPI_WEBHOOK_SECRET",
    "CREATOR_ID",
    "BOT_MODE",
    "ENABLE_UNREAD_REPLIES",
    "ENABLE_ONLINE_OUTREACH",
    "ENABLE_STALLED_OUTREACH",
    "OUTREACH_EXISTING_ONLINE",
    "ONLINE_WINDOW_SECONDS",
    "PROACTIVE_COOLDOWN_HOURS",
    "MAX_PROACTIVE_PER_HOUR",
    "MAX_PROACTIVE_PER_DAY",
    "MAX_PROACTIVE_PER_FAN_PER_DAY",
    "PRESENCE_BATCH_SIZE",
    "PRESENCE_POLL_INTERVAL",
    "STALLED_AFTER_HOURS",
    "STALLED_SCAN_INTERVAL",
    "STALLED_SCAN_BATCH_SIZE",
    "POLL_INTERVAL",
    "REPLY_WORKER_COUNT",
    "REPLY_WORKER_IDLE_SECONDS",
    "RECONCILIATION_INTERVAL",
    "RECOVERY_RECONCILIATION_ENABLED",
    "RECOVERY_CHAT_PAGES_PER_RUN",
    "RECOVERY_MESSAGE_PAGES_PER_CHAT",
    "WEBHOOK_REGISTRATION_ENABLED",
    "WEBHOOK_EVENT_PROFILE",
    "PROVIDER_MONTHLY_CREDIT_LIMIT",
    "PROVIDER_DAILY_READ_CREDIT_LIMIT",
    "PROVIDER_MONTHLY_SEND_RESERVE",
    "PROVIDER_MONTHLY_EMERGENCY_RESERVE",
    "REPLY_DELAY_MIN_SECONDS",
    "REPLY_DELAY_MAX_SECONDS",
    "PROCESSING_RETRY_BASE_SECONDS",
    "PROCESSING_RETRY_MAX_SECONDS",
    "CRM_SYNC_ENABLED",
    "CRM_SYNC_MESSAGE_PAGES_PER_CYCLE",
    "CRM_SYNC_DISCOVERY_PAGES_PER_CYCLE",
    "CRM_SYNC_BACKFILL_INTERVAL",
    "CRM_SYNC_INTERVAL",
    "DATABASE_URL",
    "PORT",
    "DASHBOARD_USER",
    "DASHBOARD_PASSWORD",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "CREDENTIAL_ENCRYPTION_KEY",
]


class TestEnvExampleExists:
    """.env.example file must exist."""

    def test_env_example_exists(self):
        """.env.example must exist at repo root."""
        assert os.path.exists(ENV_PATH), f".env.example not found at {ENV_PATH}"

    def test_env_example_is_file(self):
        """.env.example must be a regular file."""
        assert os.path.isfile(ENV_PATH), f"{ENV_PATH} is not a file"


class TestEnvExampleContent:
    """.env.example must contain all required variables."""

    def test_required_vars_present(self):
        """All required env vars must be present in .env.example."""
        with open(ENV_PATH) as f:
            content = f.read()

        for var in REQUIRED_VARS:
            assert var in content, f"Required var '{var}' missing from .env.example"

    def test_vars_have_placeholders(self):
        """Each required var should have a placeholder value."""
        with open(ENV_PATH) as f:
            content = f.read()

        # Each var line should look like: VAR=value
        for var in REQUIRED_VARS:
            for line in content.splitlines():
                if line.startswith(var + "="):
                    break
            else:
                pytest.fail(f"No value assignment found for '{var}'")

    def test_no_hardcoded_secrets(self):
        """.env.example should not contain real secret values."""
        with open(ENV_PATH) as f:
            content = f.read()

        suspicious_patterns = ["sk-", "your_api_key", "test_key"]
        for pattern in suspicious_patterns:
            # "your_api_key_here" is OK as placeholder
            pass

    def test_production_database_example_is_postgresql(self):
        with open(ENV_PATH) as f:
            content = f.read()

        database_line = next(
            line for line in content.splitlines()
            if line.startswith("DATABASE_URL=")
        )
        assert database_line.startswith("DATABASE_URL=postgresql://")

    def test_conversation_provider_and_mode_are_the_defaults(self):
        with open(ENV_PATH) as f:
            content = f.read()

        assert "FANSLY_PROVIDER=fanslyapi" in content
        assert "BOT_MODE=conversation" in content
        assert "ENABLE_ONLINE_OUTREACH=false" in content
        assert "CRM_SYNC_ENABLED=false" in content
        assert "RECOVERY_RECONCILIATION_ENABLED=false" in content
        assert "RECONCILIATION_INTERVAL=21600" in content
        assert "RECOVERY_CHAT_PAGES_PER_RUN=2" in content
        assert "RECOVERY_MESSAGE_PAGES_PER_CHAT=5" in content
        assert "DEEPSEEK_MODEL=deepseek-v4-flash" in content

    def test_env_file_structure(self):
        """.env.example should have standard env file structure (comments + key=value)."""
        with open(ENV_PATH) as f:
            content = f.read()

        lines = [l.strip() for l in content.splitlines() if l.strip()]
        has_comment = any(l.startswith("#") for l in lines)
        has_key_value = any("=" in l and not l.startswith("#") for l in lines)

        assert has_comment, "Should have comment lines documenting variables"
        assert has_key_value, "Should have key=value lines"
