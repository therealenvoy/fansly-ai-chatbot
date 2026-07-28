from src.settings.brain import BrainSettingsService
from src.settings.store import SettingsStore
from tests.web.test_dashboard import _get, _post, db_url, running_server


def _attach_brain_service(bot, db_url):
    bot.brain_settings_service = BrainSettingsService(
        settings_store=SettingsStore(
            db_url=db_url,
            creator_id=bot.creator_id,
        ),
        environment={},
        shadow_runtime=getattr(bot, "shadow_brain_service", None),
    )


def test_brain_status_and_metrics_are_authenticated_and_secret_free(
    running_server,
):
    host, bot, db_url = running_server
    _attach_brain_service(bot, db_url)

    status, body = _get(host, "/api/brain/status")
    metrics_status, metrics = _get(host, "/api/brain/metrics")

    assert status == 200
    assert body["live_authority"] == "current"
    assert body["advanced_send_blocked"] is True
    assert body["bot_enabled"] is bool(bot.enabled)
    assert body["requested_live_percent"] == 0
    assert body["deployment_live_ceiling"] == 0
    assert body["promotion_eligible"] is False
    assert metrics_status == 200
    assert metrics["source"] == "durable_brain2_records"
    assert metrics["shadow_outbox_writes"] == 0
    assert metrics["attempted_runs"] == 0
    assert metrics["completion_rate_excluding_capped"] is None
    assert metrics["provider_attempts"] == 0
    assert metrics["estimated_cost"] == 0
    assert metrics["blinded_reviews"] == 0
    rendered = str(body) + str(metrics)
    assert "api_key" not in rendered
    assert "chain-of-thought" not in rendered


def test_brain_settings_apply_without_changing_bot_enabled_state(
    running_server,
):
    host, bot, db_url = running_server
    _attach_brain_service(bot, db_url)
    bot.enabled = True

    status, body = _post(
        host,
        "/api/brain/settings",
        {
            "mode": "shadow",
            "shadow_sample_percent": 10,
            "max_strategic_calls_per_day": 100,
        },
    )

    assert status == 200
    assert body["runtime_applied"] is True
    assert body["settings"]["mode"] == "shadow"
    assert bot.enabled is True


def test_advanced_live_authority_is_rejected(running_server):
    host, bot, db_url = running_server
    _attach_brain_service(bot, db_url)

    status, body = _post(
        host,
        "/api/brain/settings",
        {"mode": "advanced"},
    )

    assert status == 400
    assert "deployment guard" in body["error"]


def test_brain_context_is_creator_scoped_and_excludes_message_drafts(
    running_server,
):
    host, bot, db_url = running_server
    _attach_brain_service(bot, db_url)

    status, body = _get(host, "/api/brain/context?fan_id=fan-a")

    assert status == 200
    assert body["fan_id"] == "fan-a"
    assert body["memories"] == []
    assert body["episodes"] == []
    assert body["decisions"] == []
    assert "draft" not in str(body)
    assert "final_message" not in str(body)


def test_brain_experiment_create_list_and_pause_are_audited(running_server):
    host, bot, db_url = running_server
    _attach_brain_service(bot, db_url)

    created_status, created = _post(
        host,
        "/api/brain/experiments",
        {
            "action": "create",
            "name": "shadow-quality-v1",
            "variants": {"control": 50, "strategic": 50},
            "minimum_sample_size": 100,
        },
    )
    paused_status, paused = _post(
        host,
        "/api/brain/experiments",
        {
            "action": "pause",
            "experiment_id": created["experiment_id"],
        },
    )
    listed_status, listed = _get(host, "/api/brain/experiments")

    assert created_status == 201
    assert created["automatic_promotion"] is False
    assert paused_status == 200
    assert paused["status"] == "paused"
    assert listed_status == 200
    experiment = listed["experiments"][0]
    assert experiment["status"] == "paused"
    assert [event["event_type"] for event in experiment["audit"]] == [
        "created",
        "paused",
    ]
    assert experiment["automatic_promotion"] is False



def test_brain_rollback_is_one_action_and_does_not_disable_bot(running_server):
    host, bot, db_url = running_server
    bot.brain_settings_service = BrainSettingsService(
        settings_store=SettingsStore(
            db_url=db_url,
            creator_id=bot.creator_id,
        ),
        environment={
            "BRAIN_ALLOW_ADVANCED_SEND": "true",
            "BRAIN_MAX_LIVE_PERCENT": "10",
        },
        shadow_runtime=getattr(bot, "shadow_brain_service", None),
    )
    bot.brain_settings_service.save(
        {"mode": "advanced", "live_percent": 0},
        actor="test",
    )
    bot.enabled = True

    status, body = _post(
        host,
        "/api/brain/rollback",
        {"reason": "operator test"},
    )

    assert status == 200
    assert body["settings"]["mode"] == "current"
    assert body["settings"]["live_percent"] == 0
    assert body["bot_enabled"] is True
