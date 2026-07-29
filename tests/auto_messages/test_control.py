from unittest.mock import MagicMock

import pytest

from src.auto_messages.control import (
    AutoMessagesControlError,
    AutoMessagesControlService,
)
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository
from src.settings.store import SettingsStore


def _control(*, online=False, stalled=False, runtime=None):
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    store = SettingsStore(engine=engine, creator_id="creator-a")
    return AutoMessagesControlService(
        settings_store=store,
        environment={
            "ENABLE_ONLINE_OUTREACH": str(online).lower(),
            "ENABLE_STALLED_OUTREACH": str(stalled).lower(),
        },
        runtime=runtime,
    )


def test_requested_activation_is_persisted_but_deployment_gate_stays_closed():
    control = _control()

    settings = control.save(
        "online",
        {
            "enabled": True,
            "max_per_hour": 3,
            "max_per_day": 15,
            "max_per_fan_per_day": 1,
        },
    )

    assert control.requested().online.enabled is True
    assert settings.online.enabled is False
    status = control.safe_status()
    assert status["deployment"]["online_allowed"] is False
    assert "Railway deployment guard" in status["blocked_reasons"]["online"]


def test_open_deployment_gate_applies_saved_settings_to_runtime():
    runtime = MagicMock()
    control = _control(online=True, stalled=True, runtime=runtime)

    settings = control.save(
        "stalled",
        {
            "enabled": True,
            "stalled_after_hours": 72,
            "scan_interval_seconds": 1800,
            "scan_batch_size": 10,
            "max_per_hour": 5,
            "max_per_day": 20,
            "max_per_fan_per_day": 1,
        },
    )

    assert settings.stalled.enabled is True
    assert settings.stalled.stalled_after_hours == 72
    runtime.update_auto_messages.assert_called_once_with(settings)


def test_fixed_mode_requires_a_message():
    control = _control(online=True)

    with pytest.raises(AutoMessagesControlError, match="requires a message"):
        control.save(
            "online",
            {
                "response_mode": "fixed",
                "fixed_message": "",
            },
        )


def test_daily_limit_cannot_be_lower_than_hourly_limit():
    control = _control(stalled=True)

    with pytest.raises(AutoMessagesControlError, match="daily limit"):
        control.save(
            "stalled",
            {
                "max_per_hour": 10,
                "max_per_day": 5,
            },
        )
