import pytest

from src.conversation.brain2 import BrainRuntimeSettings
from src.conversation.brain2_repository import BrainConfigurationAuditRepository
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



def test_live_percentage_requires_guard_advanced_mode_and_ceiling():
    service, _, _ = _service(
        {
            "BRAIN_ALLOW_ADVANCED_SEND": "true",
            "BRAIN_MAX_LIVE_PERCENT": "5",
        }
    )
    with pytest.raises(BrainSettingsError):
        service.save({"mode": "shadow", "live_percent": 1})
    with pytest.raises(BrainSettingsError):
        service.save({"mode": "advanced", "live_percent": 6})

    saved = service.save({"mode": "advanced", "live_percent": 5})
    assert saved.live_percent == 5
    assert saved.max_live_percent == 5
    assert saved.allow_advanced_send is True


def test_rollback_is_immediate_persistent_and_audited():
    service, store, runtime = _service(
        {
            "BRAIN_ALLOW_ADVANCED_SEND": "true",
            "BRAIN_MAX_LIVE_PERCENT": "10",
        }
    )
    service.save({"mode": "advanced", "live_percent": 5}, actor="operator")

    rolled_back = service.rollback(
        actor="operator",
        reason="manual kill switch",
    )

    assert rolled_back.mode == "current"
    assert rolled_back.live_percent == 0
    assert runtime.settings == rolled_back
    fresh = BrainSettingsService(
        settings_store=store,
        environment={
            "BRAIN_ALLOW_ADVANCED_SEND": "true",
            "BRAIN_MAX_LIVE_PERCENT": "10",
        },
    ).snapshot()
    assert fresh.mode == "current"
    assert fresh.live_percent == 0
    events = BrainConfigurationAuditRepository(store.engine).recent(
        creator_id=store.creator_id
    )
    assert events[0]["event_type"] == "rollback"
    assert events[0]["reason"] == "manual kill switch"
    assert "DASHBOARD_PASSWORD" not in str(events)
