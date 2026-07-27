import pytest

from src.conversation.brain2 import BrainRuntimeSettings
from src.persistence.database import create_database_engine
from src.persistence.schema import metadata
from src.settings.brain import BrainSettingsError, BrainSettingsService
from src.settings.store import SettingsStore


class ShadowRuntime:
    def __init__(self):
        self.settings = None

    def update_settings(self, settings):
        self.settings = settings


def _service(environment=None):
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    store = SettingsStore(engine=engine, creator_id="creator-a")
    runtime = ShadowRuntime()
    return (
        BrainSettingsService(
            settings_store=store,
            environment=environment or {},
            shadow_runtime=runtime,
        ),
        store,
        runtime,
    )


def test_settings_persist_and_apply_without_restart():
    service, store, runtime = _service()

    saved = service.save(
        {
            "mode": "shadow",
            "shadow_sample_percent": 10,
            "strategic_complexity_threshold": 4,
            "max_strategic_calls_per_day": 100,
        }
    )

    assert saved.mode == "shadow"
    assert runtime.settings == saved
    assert store.get_scoped("brain.mode") == "shadow"
    fresh = BrainSettingsService(
        settings_store=store,
        environment={},
    ).snapshot()
    assert fresh.shadow_sample_percent == 10


def test_advanced_mode_is_rejected_without_hard_deploy_guard():
    service, _, _ = _service()

    with pytest.raises(BrainSettingsError):
        service.save({"mode": "advanced"})


def test_environment_ceiling_limits_dashboard_shadow_percentage():
    service, _, _ = _service(
        {"BRAIN_MAX_SHADOW_SAMPLE_PERCENT": "20"}
    )

    with pytest.raises(BrainSettingsError):
        service.save(
            {
                "mode": "shadow",
                "shadow_sample_percent": 21,
            }
        )


def test_safe_default_keeps_current_live_authority():
    service, _, _ = _service()

    assert service.snapshot() == BrainRuntimeSettings()
