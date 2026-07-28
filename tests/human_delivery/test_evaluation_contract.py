import json
from pathlib import Path


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "human_delivery_eval_v1.json"
)


def test_synthetic_evaluation_set_is_versioned_and_complete():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["version"] == "human-delivery-eval-v1"
    assert payload["safety_class"] == "synthetic_conversation_only"
    cases = payload["cases"]
    assert len(cases) >= 25
    ids = {case["id"] for case in cases}
    assert {
        "multi_message_turn",
        "emotional_disclosure",
        "boundary_sensitive",
        "creator_fact_question",
        "non_english",
        "code_switching",
        "bot_accusation",
        "manual_interruption",
        "deleted_inbound",
        "duplicate_event",
        "out_of_order",
    } <= ids
    assert len(ids) == len(cases)


def test_synthetic_evaluation_set_has_no_live_authority_or_sales_cases():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    encoded = json.dumps(payload).casefold()
    assert "ppv" not in encoded
    assert "price" not in encoded
    assert "send_media" not in encoded
    assert all(
        "expected_act" in case
        and ("turn" in case or "events" in case)
        for case in payload["cases"]
    )
