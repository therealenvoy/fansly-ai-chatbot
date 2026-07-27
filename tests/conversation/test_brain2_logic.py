from src.conversation.brain2 import (
    BrainRouter,
    BrainRuntimeSettings,
    ConversationQualityGate,
)


def test_router_selects_strategic_for_vulnerability_and_stalled_turns():
    router = BrainRouter()

    vulnerable = router.route(
        fan_message="I feel really alone and don't know what to do",
        trigger_kind="unread",
        history="",
        has_memory_conflict=False,
        failed_tactic_count=0,
        context_confidence=1.0,
    )
    stalled = router.route(
        fan_message="",
        trigger_kind="stalled",
        history="Creator: how was work?",
        has_memory_conflict=False,
        failed_tactic_count=0,
        context_confidence=1.0,
    )

    assert vulnerable.path == "strategic"
    assert "vulnerability" in vulnerable.reasons
    assert stalled.path == "strategic"
    assert "stalled_reopening" in stalled.reasons


def test_quality_gate_rejects_sales_tracking_repetition_and_question_streak():
    gate = ConversationQualityGate()

    sales = gate.evaluate("unlock this for $20", recent_creator_messages=[])
    tracking = gate.evaluate(
        "I saw you came online again",
        recent_creator_messages=[],
    )
    repeated = gate.evaluate(
        "how was your day babe?",
        recent_creator_messages=["how was your day babe?"],
    )
    questions = gate.evaluate(
        "what are you doing?",
        recent_creator_messages=[],
        question_streak=2,
    )

    assert "sales_or_ppv" in sales.reason_codes
    assert "online_tracking" in tracking.reason_codes
    assert "excessive_similarity" in repeated.reason_codes
    assert "question_streak" in questions.reason_codes


def test_runtime_settings_are_safe_by_default_and_clamped():
    settings = BrainRuntimeSettings.from_mapping(
        {
            "BRAIN_MODE": "advanced",
            "BRAIN_SHADOW_SAMPLE_PERCENT": "900",
            "BRAIN_MAX_MODEL_CALLS_PER_TURN": "50",
            "BRAIN_JSON_REPAIR_ATTEMPTS": "9",
        }
    )

    assert settings.mode == "advanced"
    assert settings.shadow_sample_percent == 100
    assert settings.max_model_calls_per_turn == 4
    assert settings.json_repair_attempts == 1
