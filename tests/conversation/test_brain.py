import json

from src.conversation.brain import ConversationDecision


def test_structured_decision_parses_and_clamps_fields():
    decision = ConversationDecision.from_model_output(
        json.dumps(
            {
                "fan_state": "engaged",
                "state_summary": "Fan shared a concrete detail about work.",
                "objective": "deepen",
                "tactic": "callback",
                "open_thread": "Their late shift",
                "draft": "rough draft",
                "critique": ["Too generic", "Use the work detail"],
                "final_message": "did that late shift get any easier babe?",
                "confidence": 1.7,
            }
        ),
        proactive_kind=None,
    )

    assert decision is not None
    assert decision.objective == "deepen"
    assert decision.tactic == "callback"
    assert decision.critique == (
        "Too generic",
        "Use the work detail",
    )
    assert decision.confidence == 1.0


def test_unknown_strategy_values_fall_back_safely():
    decision = ConversationDecision.from_model_output(
        json.dumps(
            {
                "objective": "manipulate",
                "tactic": "pressure",
                "final_message": "how did your evening go?",
            }
        ),
        proactive_kind="stalled",
    )

    assert decision is not None
    assert decision.objective == "reconnect"
    assert decision.tactic == "gentle_check_in"


def test_plain_text_uses_legacy_fallback_but_malformed_json_fails_closed():
    fallback = ConversationDecision.from_model_output(
        "how was work babe?",
        proactive_kind=None,
    )

    assert fallback is not None
    assert fallback.final_message == "how was work babe?"
    assert fallback.confidence == 0.25
    assert ConversationDecision.from_model_output(
        '{"final_message":',
        proactive_kind=None,
    ) is None
