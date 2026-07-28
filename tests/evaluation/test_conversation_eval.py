import json
from pathlib import Path

from src.evaluation.conversation import EvaluationRunner


def test_evaluation_reports_deterministic_errors_and_pairwise_results(tmp_path):
    fixture = tmp_path / "cases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "id": "greeting",
                    "recent_creator_messages": [],
                    "question_streak": 0,
                    "pet_name_streak": 0,
                    "acceptable_objectives": ["answer", "deepen"],
                    "required_observations": ["day"],
                    "forbidden_mistakes": ["unlock"],
                    "variants": {
                        "current": {
                            "objective": "answer",
                            "message": "hey",
                        },
                        "improved_fast": {
                            "objective": "deepen",
                            "message": "how was your day?",
                        },
                        "strategic": {
                            "objective": "deepen",
                            "message": "tell me about your day?",
                        },
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    result = EvaluationRunner().run_file(fixture)

    assert result["case_count"] == 1
    assert result["evidence_scope"] == "synthetic_deterministic_regression"
    assert "does not prove live reply-rate" in EvaluationRunner.markdown(result)
    assert result["variants"]["improved_fast"]["deterministic_errors"] == 0
    assert result["variants"]["strategic"]["deterministic_errors"] == 0
    assert result["pairwise"]["improved_fast_vs_current"]["wins"] == 1
    assert result["pairwise"]["strategic_vs_current"]["wins"] == 1


def test_repository_fixture_suite_contains_complete_synthetic_context():
    fixtures = json.loads(
        Path("evals/conversation_v1.json").read_text(encoding="utf-8")
    )
    required = {
        "persona",
        "instructions",
        "brand_bible",
        "history",
        "memory",
        "conversation_state",
        "new_inbound_message",
        "trigger_kind",
        "acceptable_objectives",
        "required_observations",
        "forbidden_mistakes",
        "quality_rubric",
        "variants",
    }

    assert len(fixtures) >= 21
    assert all(required <= set(case) for case in fixtures)
    assert "closed_thread" in {case["id"] for case in fixtures}
