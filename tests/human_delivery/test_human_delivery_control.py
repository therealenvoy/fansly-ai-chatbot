from sqlalchemy import create_engine

from src.human_delivery.control import (
    HumanDeliveryControlError,
    HumanDeliveryControlService,
)
from src.persistence.schema import metadata
from src.settings.store import SettingsStore


def _store():
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata.create_all(engine)
    return SettingsStore(engine=engine, creator_id="creator-a")


def test_database_request_cannot_override_disabled_deployment():
    store = _store()
    store.set_many(
        {
            "human_delivery.enabled": "true",
            "human_delivery.mode": "live",
            "human_delivery.live_percent": "100",
        }
    )
    control = HumanDeliveryControlService(
        settings_store=store,
        environment={
            "HUMAN_DELIVERY_ENABLED": "false",
            "HUMAN_DELIVERY_MAX_LIVE_PERCENT": "0",
        },
    )
    settings = control.snapshot()
    assert settings.enabled is False
    assert settings.mode == "off"
    assert settings.live_percent == 0
    assert settings.live_authority is False


def test_save_rejects_authority_above_deployment_ceiling():
    control = HumanDeliveryControlService(
        settings_store=_store(),
        environment={"HUMAN_DELIVERY_ENABLED": "false"},
    )
    try:
        control.save({"enabled": True})
    except HumanDeliveryControlError as error:
        assert "deployment guard" in str(error)
    else:
        raise AssertionError("deployment guard should reject enablement")


def test_shadow_request_within_ceiling_updates_runtime():
    class Runtime:
        settings = None

        def update_settings(self, settings):
            self.settings = settings

    runtime = Runtime()
    control = HumanDeliveryControlService(
        settings_store=_store(),
        environment={
            "HUMAN_DELIVERY_ENABLED": "true",
            "HUMAN_DELIVERY_MODE": "shadow",
            "HUMAN_DELIVERY_SHADOW_PERCENT": "10",
        },
        runtime=runtime,
    )
    settings = control.save(
        {
            "enabled": True,
            "mode": "shadow",
            "shadow_percent": 5,
        }
    )
    assert settings.shadow_authority is True
    assert settings.shadow_percent == 5
    assert runtime.settings == settings
