from src.settings.brain import BrainSettingsService
from src.settings.store import SettingsStore
from src.web.dashboard import DASHBOARD_HTML, DashboardHandler
from tests.web.test_dashboard import _get, _post, db_url, running_server


def test_dashboard_document_has_one_terminal_html_close():
    normalized = DASHBOARD_HTML.strip().lower()

    assert normalized.count("</html>") == 1
    assert normalized.endswith("</html>")


def test_brain_dashboard_renders_required_operational_evidence_labels():
    for label in (
        "Bot enabled",
        "Authority / mode",
        "Requested / ceiling / shadow",
        "Advanced guard / rollback",
        "Brain version / deployment",
        "Failure categories",
        "Fast latency",
        "Strategic latency",
        "Provider calls",
        "Tokens",
        "Outbox safety",
        "Delivered outcomes",
    ):
        assert label in DASHBOARD_HTML


def _promotion_metrics():
    return {
        "shadow_outbox_writes": 0,
        "max_daily_cost": 5.0,
        "promotion_window": {
            "attempted_runs": 200,
            "completion_rate_excluding_capped": 0.995,
            "unclassified_failures": 0,
            "json_schema_failures": 0,
            "json_schema_failure_rate": 0,
            "timeout_rate_limit_rate": 0.01,
            "fast_p95_latency_ms": 7000,
            "strategic_p95_latency_ms": 19000,
            "approved_safety_violations": 0,
            "provider_attempts": 200,
            "fast_average_cost": 0.001,
            "strategic_average_cost": 0.003,
        },
        "review_window": {
            "blinded_reviews": 200,
            "advanced_non_tied_win_rate": 0.55,
            "advanced_safety_hard_failures": 0,
            "advanced_hard_failures_by_code": {},
        },
    }


def test_promotion_uses_current_version_windows_not_all_time_history():
    metrics = _promotion_metrics()
    metrics.update(
        {
            "attempted_runs": 999,
            "completion_rate_excluding_capped": 0.25,
            "json_schema_failures": 500,
            "blinded_reviews": 999,
            "advanced_non_tied_win_rate": 0.1,
        }
    )

    result = DashboardHandler._brain_promotion_readiness(metrics)

    assert result == {"eligible": True, "unmet": []}


def test_promotion_rejects_one_malformed_output_in_latest_200():
    metrics = _promotion_metrics()
    metrics["promotion_window"]["json_schema_failures"] = 1
    metrics["promotion_window"]["json_schema_failure_rate"] = 0.005

    result = DashboardHandler._brain_promotion_readiness(metrics)

    assert result["eligible"] is False
    assert "zero_malformed_json_last_200" in result["unmet"]
    assert "json_schema_below_half_percent" in result["unmet"]


def test_promotion_rejects_advanced_review_safety_failure():
    metrics = _promotion_metrics()
    metrics["review_window"]["advanced_safety_hard_failures"] = 1

    result = DashboardHandler._brain_promotion_readiness(metrics)

    assert result["eligible"] is False
    assert "zero_approved_safety_violations" in result["unmet"]


def test_promotion_rejects_persona_or_repetition_regression():
    metrics = _promotion_metrics()
    metrics["review_window"]["advanced_hard_failures_by_code"] = {
        "persona_regression": 1,
        "excessive_repetition": 1,
    }

    result = DashboardHandler._brain_promotion_readiness(metrics)

    assert result["eligible"] is False
    assert "no_advanced_persona_regression" in result["unmet"]
    assert "no_advanced_repetition_regression" in result["unmet"]


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
    assert metrics["duplicate_outbox_writes"] == 0
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


def test_explicit_operator_override_allows_live_before_promotion(
    running_server,
    monkeypatch,
):
    host, bot, db_url = running_server
    monkeypatch.setenv("BRAIN_OPERATOR_PROMOTION_OVERRIDE", "true")
    bot.brain_settings_service = BrainSettingsService(
        settings_store=SettingsStore(
            db_url=db_url,
            creator_id=bot.creator_id,
        ),
        environment={
            "BRAIN_ALLOW_ADVANCED_SEND": "true",
            "BRAIN_MAX_LIVE_PERCENT": "100",
            "BRAIN_MAX_SHADOW_SAMPLE_PERCENT": "100",
        },
        shadow_runtime=getattr(bot, "shadow_brain_service", None),
    )

    status, body = _post(
        host,
        "/api/brain/settings",
        {
            "mode": "advanced",
            "live_percent": 100,
            "max_daily_cost": 10,
            "operator_override": True,
        },
    )

    assert status == 200
    assert body["operator_override_used"] is True
    assert body["settings"]["mode"] == "advanced"
    assert body["settings"]["live_percent"] == 100


def test_live_before_promotion_still_rejects_without_explicit_override(
    running_server,
    monkeypatch,
):
    host, bot, db_url = running_server
    monkeypatch.setenv("BRAIN_OPERATOR_PROMOTION_OVERRIDE", "true")
    bot.brain_settings_service = BrainSettingsService(
        settings_store=SettingsStore(
            db_url=db_url,
            creator_id=bot.creator_id,
        ),
        environment={
            "BRAIN_ALLOW_ADVANCED_SEND": "true",
            "BRAIN_MAX_LIVE_PERCENT": "100",
        },
        shadow_runtime=getattr(bot, "shadow_brain_service", None),
    )

    status, body = _post(
        host,
        "/api/brain/settings",
        {
            "mode": "advanced",
            "live_percent": 100,
            "max_daily_cost": 10,
        },
    )

    assert status == 409
    assert body["operator_override_available"] is True


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
