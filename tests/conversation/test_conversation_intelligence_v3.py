from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, insert, select

from src.conversation.intelligence_v3.diversity import GlobalDiversityGate
from src.conversation.intelligence_v3.knowledge import (
    ExtractedDocument,
    ExtractedPage,
    KnowledgeIngestionError,
    extract_pdf,
)
from src.conversation.intelligence_v3.outcomes import (
    composite_quality,
    observe_reply,
    plan_bubbles,
)
from src.conversation.intelligence_v3.contracts import HighEQPlan
from src.conversation.intelligence_v3.planner import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_TOKENS,
    DeepSeekV3Planner,
    PlanEnvelope,
    PlannerResult,
    PromptCompilerV3,
    V3PlannerError,
)
from src.conversation.intelligence_v3.retrieval import MemoryRetrieverV3
from src.conversation.intelligence_v3.repository import (
    IntelligenceRepository,
    KnowledgeRepository,
)
from src.conversation.intelligence_v3.service import ConversationIntelligenceV3Service
from src.conversation.intelligence_v3.settings import V3RuntimeSettings
from src.conversation.intelligence_v3.state import (
    RelationshipStateReducer,
    infer_callback,
    infer_deterministic_proposal,
)
from src.evaluation.conversation_intelligence_v3 import (
    FROZEN_CASE_COUNT,
    FROZEN_SUITE_FINGERPRINT,
    SEEDS,
    evaluate_candidate_artifact,
    frozen_cases,
    pending_evaluation_summary,
)
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.conversation.intelligence_v3.schema import CONVERSATION_INTELLIGENCE_RUNS
from src.persistence.schema import CREATORS, OUTBOX_MESSAGES, metadata, utcnow
from src.persistence.state import ConversationStateRepository
from src.conversation.brain2_memory import ExtractedMemoryWriter
from src.conversation.brain2_repository import FanMemoryV2Repository


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    now = utcnow()
    with engine.begin() as connection:
        connection.execute(
            insert(CREATORS).values(
                id="creator-a",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(CREATORS).values(
                id="creator-b",
                created_at=now,
                updated_at=now,
            )
        )
    return engine


def _extracted(name="playbook.pdf"):
    content = "When a fan corrects a detail, acknowledge the correction before continuing."
    return ExtractedDocument(
        name=name,
        mime_type="application/pdf",
        fingerprint=("a" if name == "playbook.pdf" else "b") * 64,
        pages=(
            ExtractedPage(
                page_number=1,
                content=content,
                fingerprint="c" * 64,
                quality=1.0,
                unreadable=False,
            ),
        ),
        status="complete",
        report={"page_count": 1, "readable_pages": 1, "ocr_used": False},
    )


def test_feature_ceilings_fail_closed_and_never_grant_outbox_authority():
    settings = V3RuntimeSettings.from_mappings(
        {
            "PLAYBOOK_ENGINE_MODE": "shadow",
            "RELATIONSHIP_STATE_V2_MODE": "shadow",
            "STRATEGY_PLANNER_V2_MODE": "shadow",
            "CONVERSATION_INTELLIGENCE_V3_ALLOW_SEND": "false",
        },
        {
            "PLAYBOOK_ENGINE_MODE": "live",
            "RELATIONSHIP_STATE_V2_MODE": "live",
            "STRATEGY_PLANNER_V2_MODE": "live",
        },
    )

    assert settings.playbook_engine_mode == "shadow"
    assert settings.relationship_state_v2_mode == "shadow"
    assert settings.strategy_planner_v2_mode == "shadow"
    assert settings.live_send_authority is False
    assert settings.safe_status()["outbox_write_capability"] is False


def test_live_authority_requires_every_core_ceiling_and_bounded_percentage():
    settings = V3RuntimeSettings.from_mappings(
        {
            "PLAYBOOK_ENGINE_MODE": "live",
            "RELATIONSHIP_STATE_V2_MODE": "live",
            "MEMORY_RETRIEVAL_V3_MODE": "live",
            "STRATEGY_PLANNER_V2_MODE": "live",
            "GLOBAL_DIVERSITY_MODE": "live",
            "OUTCOME_LEARNING_MODE": "observe",
            "MULTI_BUBBLE_MODE": "shadow",
            "CONVERSATION_INTELLIGENCE_V3_ALLOW_SEND": "true",
            "CONVERSATION_INTELLIGENCE_V3_LIVE_PERCENT": "100",
            "CONVERSATION_INTELLIGENCE_V3_MAX_LIVE_PERCENT": "100",
            "CONVERSATION_INTELLIGENCE_V3_MAX_DAILY_COST": "10",
        }
    )

    assert settings.live_send_authority is True
    assert settings.live_percent == 100
    assert settings.max_live_percent == 100
    assert settings.max_daily_cost == 10
    assert settings.multi_bubble_mode == "shadow"
    assert settings.safe_status()["outbox_write_capability"] is False


def test_prompt_compiler_honors_total_budget_and_priority():
    compiler = PromptCompilerV3()
    compiled = compiler.compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "newest evidence",
            "direct_unresolved_question": "what happened?",
            "recent_history": "h" * 80_000,
            "relationship_state": {"active_topic": "interview", "notes": "n" * 40_000},
            "boundaries": [{"forbidden_acts": ["pressure"]}],
            "verified_creator_facts": [{"fact_key": "city", "fact_value": "source backed"}],
            "creator_instructions": "i" * 80_000,
        },
        max_tokens=MAX_CONTEXT_TOKENS,
    )

    assert compiled.context["safety"] == {"conversation_only": True}
    assert compiled.context["newest_turn"] == "newest evidence"
    assert compiled.context["direct_unresolved_question"] == "what happened?"
    assert isinstance(compiled.context["relationship_state"], dict)
    assert isinstance(compiled.context["boundaries"], list)
    assert set(compiled.report["required_sections_present"]) == set(
        PromptCompilerV3.required_sections
    )
    assert compiled.report["used_chars"] <= MAX_CONTEXT_CHARS
    assert compiled.report["estimated_tokens"] <= MAX_CONTEXT_TOKENS
    assert "recent_history" in compiled.report["truncated_sections"]


def test_planner_rejects_pro_model_and_multi_bubble_stays_inert():
    with pytest.raises(ValueError, match="does not allow DeepSeek Pro"):
        DeepSeekV3Planner(api_key="secret", model="deepseek-v4-pro")

    plan = plan_bubbles(
        "first reaction. second substantive thought? third close.",
        requested=3,
        mode="live",
    )
    assert plan.shadow_only is True
    assert plan.bubble_count <= 3


def _planner_payload(messages):
    acts = ("support", "learn", "reassure")
    structures = ("direct_warm", "specific_reflection", "grounded_statement")
    return {
        "understanding": {
            "emotion": "nervous",
            "intent": "seek_support",
            "active_thread": "interview",
            "underlying_need": "reassurance",
            "direct_question": None,
            "evidence": [
                {
                    "source_message_id": "current",
                    "observation": "explicit nervous wording",
                    "confidence": 0.95,
                }
            ],
        },
        "relationship": {
            "stage": "recognition",
            "trust": 0.2,
            "familiarity": 0.2,
            "warmth": 0.4,
            "reciprocity": 0.2,
            "playfulness": 0.1,
            "emotional_depth": 0.2,
            "fantasy_openness": 0.0,
            "question_fatigue": 0.0,
            "pet_name_tolerance": "unknown",
            "momentum": "steady",
            "intimacy_ceiling": "warm",
            "evidence": [],
        },
        "strategy": {
            "primary_act": "support",
            "secondary_act": "learn",
            "must_reference": ["interview"],
            "must_avoid": ["invented reassurance"],
            "should_ask_question": False,
            "desired_effect": "help the fan feel understood",
        },
        "delivery": {
            "bubble_count": 1,
            "energy": "medium",
            "length": "short",
            "emoji_budget": 0,
        },
        "candidates": [
            {
                "candidate_id": f"c{index}",
                "act": acts[index - 1],
                "structure": structures[index - 1],
                "message": message,
            }
            for index, message in enumerate(messages, start=1)
        ],
    }


class _PlannerResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": json.dumps(self.payload)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40},
        }


class _RawPlannerResponse(_PlannerResponse):
    def __init__(self, content, *, outer=None):
        self.content = content
        self.outer = outer

    def json(self):
        if self.outer is not None:
            return self.outer
        return {
            "choices": [{"message": {"content": self.content}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40},
        }


def test_fast_planner_generates_two_distinct_candidates_in_one_call():
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs["json"])
        return _PlannerResponse(
            _planner_payload(
                [
                    "interview nerves are real... i'm listening",
                    "the interview matters to u, and that makes sense",
                ]
            )
        )

    planner = DeepSeekV3Planner(api_key="secret", request=request)
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "i feel nervous about my interview tomorrow",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [],
        }
    )
    result = planner.generate(
        compiled,
        strategic=False,
        recent_fan_messages=[],
        recent_creator_messages=[],
    )

    assert len(calls) == 1
    assert calls[0]["messages"][1]["content"].find('"candidate_count":2') >= 0
    assert len(result.plan.candidates) == 2
    assert result.selected_message is not None
    assert result.model_calls == 1
    assert result.selection_mode == "model_candidate"


def test_transport_adapter_accepts_fenced_json_extra_fields_and_one_candidate():
    payload = _planner_payload(["interview nerves make sense when it matters"])
    payload["provider_note"] = "ignored transport metadata"
    payload["strategy"]["provider_note"] = "ignored nested metadata"
    payload["candidates"][0]["provider_note"] = "ignored candidate metadata"

    planner = DeepSeekV3Planner(
        api_key="secret",
        request=lambda *args, **kwargs: _RawPlannerResponse(
            "```json\n" + json.dumps(payload) + "\n```"
        ),
    )
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "i feel nervous about my interview tomorrow",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [],
        }
    )

    result = planner.generate(
        compiled,
        strategic=False,
        recent_fan_messages=[],
        recent_creator_messages=[],
    )

    assert result.selected_message == "interview nerves make sense when it matters"
    assert result.model_calls == 1
    assert "provider_json_fence_stripped" in result.degradation_codes
    assert "provider_extra_fields_ignored" in result.degradation_codes
    assert "candidate_count_degraded" in result.degradation_codes


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda payload: payload["relationship"].update(stage="not-a-stage"),
            "provider_contract_enum_invalid",
        ),
        (
            lambda payload: payload["strategy"].pop("desired_effect"),
            "provider_contract_missing_required",
        ),
    ],
)
def test_transport_adapter_reports_safe_specific_contract_failures(
    mutate,
    expected_code,
):
    payload = _planner_payload(
        [
            "interview nerves are real and i'm listening",
            "the interview matters to u and that makes sense",
        ]
    )
    mutate(payload)
    planner = DeepSeekV3Planner(
        api_key="secret",
        request=lambda *args, **kwargs: _RawPlannerResponse(json.dumps(payload)),
    )
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "i feel nervous",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [],
        }
    )

    with pytest.raises(V3PlannerError) as raised:
        planner.generate(
            compiled,
            strategic=False,
            recent_fan_messages=[],
            recent_creator_messages=[],
        )

    assert raised.value.code == expected_code
    assert raised.value.diagnostic["schema"] == "plan"
    assert "raw_content" not in raised.value.diagnostic
    assert raised.value.model_calls == 1


def test_transport_adapter_distinguishes_truncated_json_from_outer_shape_errors():
    planner = DeepSeekV3Planner(api_key="secret")

    with pytest.raises(V3PlannerError) as truncated:
        planner._call(
            instruction="return a plan",
            payload={},
            schema=PlanEnvelope,
            request=lambda *args, **kwargs: _RawPlannerResponse('{"understanding":'),
        )
    assert truncated.value.code == "provider_content_json_truncated"

    with pytest.raises(V3PlannerError) as shape:
        planner._call(
            instruction="return a plan",
            payload={},
            schema=PlanEnvelope,
            request=lambda *args, **kwargs: _RawPlannerResponse(
                "",
                outer={"choices": []},
            ),
        )
    assert shape.value.code == "provider_response_shape_invalid"


def test_invalid_strategic_judge_uses_deterministic_safe_candidate_without_third_call():
    responses = [
        _PlannerResponse(
            _planner_payload(
                [
                    "interview nerves are real and i'm listening",
                    "the interview matters to u and that makes sense",
                    "u care about tomorrow, so the nerves make sense",
                ]
            )
        ),
        _RawPlannerResponse("```json\n{\"assessments\":\n```"),
    ]
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs["json"])
        return responses[len(calls) - 1]

    planner = DeepSeekV3Planner(api_key="secret", request=request)
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "i feel nervous about my interview tomorrow",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [],
        }
    )

    result = planner.generate(
        compiled,
        strategic=True,
        recent_fan_messages=[],
        recent_creator_messages=[],
    )

    assert len(calls) == 2
    assert result.selected_message is not None
    assert result.selection_mode == "deterministic_judge_fallback"
    assert "judge_provider_content_json_truncated" in result.degradation_codes


def test_all_rejected_fast_candidates_use_only_evidence_grounded_fallback():
    repeated = [
        "got it... i'll respect that",
        "please stop, i hear u and i'll back off",
    ]

    def request(*args, **kwargs):
        return _PlannerResponse(_planner_payload(repeated))

    planner = DeepSeekV3Planner(api_key="secret", request=request)
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "please stop, this is too much",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {"boundary_signal": "stop"},
            "boundaries": [{"forbidden_acts": ["pressure"]}],
            "verified_creator_facts": [],
        }
    )
    result = planner.generate(
        compiled,
        strategic=False,
        recent_fan_messages=[],
        recent_creator_messages=repeated,
    )

    assert result.selected_message == "got it... i'll respect that"
    assert result.selection_mode == "grounded_fallback"
    assert result.fallback_reason == "explicit_boundary_acknowledgement"
    assert result.requires_operator_review is False


def test_fast_path_rejects_candidate_that_does_not_answer_direct_question():
    payload = _planner_payload(
        ["that sounds interesting", "i live in new york, what about u?"]
    )
    payload["understanding"]["direct_question"] = "where do you live?"
    payload["candidates"][1]["addresses_direct_question"] = True
    payload["strategy"]["should_ask_question"] = True

    planner = DeepSeekV3Planner(
        api_key="secret",
        request=lambda *args, **kwargs: _PlannerResponse(payload),
    )
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "where do you live?",
            "direct_unresolved_question": "where do you live?",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [{"city": "new york"}],
        }
    )
    result = planner.generate(
        compiled,
        strategic=False,
        recent_fan_messages=[],
        recent_creator_messages=[],
    )

    assert result.selected_candidate_id == "c2"
    assert "ignored_direct_question" in result.rejection_codes


def test_fast_path_applies_deterministic_safety_gate_without_a_second_call():
    payload = _planner_payload(
        ["i just got home from the gym", "unlock my ppv for $10"]
    )
    planner = DeepSeekV3Planner(
        api_key="secret",
        request=lambda *args, **kwargs: _PlannerResponse(payload),
    )
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "hey",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [],
        }
    )

    result = planner.generate(
        compiled,
        strategic=False,
        recent_fan_messages=[],
        recent_creator_messages=[],
    )

    assert result.selected_message is None
    assert result.requires_operator_review is True
    assert result.model_calls == 1
    assert "invented_real_world_activity" in result.rejection_codes
    assert "sales_or_ppv" in result.rejection_codes


def test_strategic_judge_regenerates_once_inside_two_call_ceiling():
    original_messages = [
        "i hear you and that makes sense right now",
        "i understand and that makes sense right now",
        "i get you and that makes sense right now",
    ]
    responses = [
        _planner_payload(original_messages),
        {
            "assessments": [
                {
                    "candidate_id": f"c{index}",
                    "scores": {"relevance": 4.0},
                    "rejection_codes": ["canned_empathy"],
                    "approved": False,
                }
                for index in range(1, 4)
            ],
            "winner_id": None,
            "all_rejected": True,
            "replacement_candidate": {
                "candidate_id": "r1",
                "act": "support",
                "structure": "specific_observation",
                "message": "the interview clearly matters to u... nerves don't erase how prepared u are",
                "addresses_direct_question": False,
            },
            "replacement_assessment": {
                "candidate_id": "r1",
                "scores": {"relevance": 9.0, "grounding": 9.0},
                "rejection_codes": [],
                "approved": True,
            },
        },
    ]
    calls = []

    def request(*args, **kwargs):
        calls.append(kwargs["json"])
        return _PlannerResponse(responses[len(calls) - 1])

    planner = DeepSeekV3Planner(api_key="secret", request=request)
    compiled = PromptCompilerV3().compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "i feel nervous about my interview tomorrow",
            "direct_unresolved_question": "",
            "recent_history": [],
            "relationship_state": {},
            "boundaries": [],
            "verified_creator_facts": [],
        }
    )
    result = planner.generate(
        compiled,
        strategic=True,
        recent_fan_messages=[],
        recent_creator_messages=original_messages,
    )

    assert len(calls) == 2
    assert result.model_calls == 2
    assert result.selected_candidate_id == "r1"
    assert result.selection_mode == "model_candidate"
    assert any(item.candidate_id == "r1" for item in result.plan.candidates)


def test_state_reducer_rejects_duplicate_and_stale_evidence_and_captures_callback():
    reducer = RelationshipStateReducer()
    when = datetime(2026, 8, 1, tzinfo=timezone.utc)
    proposal = infer_deterministic_proposal(
        message="i feel nervous about my interview tomorrow",
        source_message_id="message-1",
        source_timestamp=when,
    )
    first = reducer.reduce({}, proposal)
    duplicate = reducer.reduce(first.state, proposal)
    stale = reducer.reduce(
        first.state,
        infer_deterministic_proposal(
            message="older content",
            source_message_id="message-0",
            source_timestamp=when - timedelta(seconds=1),
        ),
    )
    callback = infer_callback(
        message="my interview is tomorrow",
        source_message_id="message-1",
        source_timestamp=when,
    )

    assert first.accepted is True
    assert first.state["relationship_stage"] == "recognition"
    assert first.state["current_emotion"] == "vulnerable"
    assert first.state["current_energy"] == "medium"
    assert first.state["active_topic"] == "interview"
    assert first.state["future_callback"] == "interview"
    assert first.state["recommended_next_act"] == "support"
    assert duplicate.reason == "stale_source"
    assert stale.reason == "stale_source"
    assert callback is not None
    assert callback["subject_key"] == "interview"
    assert infer_callback(
        message="nothing scheduled",
        source_message_id="message-2",
        source_timestamp=when,
    ) is None


def test_shadow_state_accumulates_without_mutating_live_state_and_callback_cools_down():
    engine = _engine()
    repository = IntelligenceRepository(engine, creator_id="creator-a")
    reducer = RelationshipStateReducer()
    when = datetime.now(timezone.utc) - timedelta(hours=2)
    first = reducer.reduce(
        {},
        infer_deterministic_proposal(
            message="i feel nervous about my interview tomorrow",
            source_message_id="message-1",
            source_timestamp=when,
        ),
    )
    for transition in first.transitions:
        repository.record_transition(fan_id="fan-a", transition=transition)
    overlay = repository.shadow_state(
        fan_id="fan-a",
        base={"relationship_stage": "unknown", "state_version": 1},
    )
    second = reducer.reduce(
        overlay,
        infer_deterministic_proposal(
            message="i'm calmer now and ready for it",
            source_message_id="message-2",
            source_timestamp=when + timedelta(minutes=5),
            previous=overlay,
        ),
    )
    for transition in second.transitions:
        repository.record_transition(fan_id="fan-a", transition=transition)
    accumulated = repository.shadow_state(
        fan_id="fan-a",
        base={"relationship_stage": "unknown", "state_version": 1},
    )
    callback_id = repository.upsert_callback(
        fan_id="fan-a",
        callback={
            "subject": "interview tomorrow",
            "subject_key": "interview",
            "source_message_id": "message-1",
            "first_mentioned_at": when,
            "earliest_safe_reuse_at": when,
            "current_relevance": 0.8,
        },
    )
    assert repository.relevant_callbacks(fan_id="fan-a", limit=2)
    assert repository.mark_callback_used(
        fan_id="fan-a",
        callback_id=callback_id,
        used_at=datetime.now(timezone.utc),
    )

    assert accumulated["last_source_message_id"] == "message-2"
    assert accumulated["version"] == 2
    assert accumulated["current_energy"] == "medium"
    assert repository.relevant_callbacks(fan_id="fan-a", limit=2) == []


def test_knowledge_is_versioned_source_backed_creator_scoped_and_sales_excluded():
    engine = _engine()
    repository = KnowledgeRepository(engine, creator_id="creator-a")
    document = repository.ingest(_extracted())
    cached = repository.ingest(_extracted())
    conversation_rule = repository.create_rule(
        {
            "rule_key": "repair-correction",
            "knowledge_profile": "conversation",
            "knowledge_type": "decision_rule",
            "scenario": "fan_correction",
            "source_document_id": document["id"],
            "source_page": 1,
            "search_text": "acknowledge correction before continuing",
            "recommended_acts": ["repair"],
            "forbidden_acts": ["defend error"],
            "status": "active",
        }
    )
    repository.create_rule(
        {
            "rule_key": "sales-rule",
            "knowledge_profile": "sales",
            "knowledge_type": "decision_rule",
            "scenario": "offer",
            "source_document_id": document["id"],
            "source_page": 1,
            "search_text": "sell an offer",
            "recommended_acts": ["sell"],
            "status": "active",
        }
    )
    retrieved = repository.retrieve(
        query="you got that detail wrong",
        relationship_stage="repair_needed",
        profiles=("conversation", "relationship", "sales"),
    )
    other_creator = KnowledgeRepository(engine, creator_id="creator-b").overview()

    assert cached["cached"] is True
    assert any(row["id"] == conversation_rule["id"] for row in retrieved["rules"])
    assert all(row["knowledge_profile"] != "sales" for row in retrieved["rules"])
    assert other_creator["documents"] == []


def test_knowledge_boundaries_are_always_retrieved_and_document_revisions_roll_back():
    engine = _engine()
    repository = KnowledgeRepository(engine, creator_id="creator-a")
    first = repository.ingest(_extracted(), actor="original-uploader")
    second = repository.ingest(_extracted("second.pdf"), actor="original-uploader")
    assert first["document_type"] == "conversation_playbook"
    assert second["revision"] == 2
    repository.set_document_status(first["id"], status="active", actor="owner")
    repository.set_document_status(second["id"], status="active", actor="owner")
    documents = repository.overview()["documents"]
    statuses = {row["id"]: row["status"] for row in documents}
    assert statuses[first["id"]] == "archived"
    assert statuses[second["id"]] == "active"
    assert next(
        row["created_by"] for row in documents if row["id"] == second["id"]
    ) == "original-uploader"
    repository.create_rule(
        {
            "rule_key": "respect-boundary",
            "knowledge_profile": "conversation",
            "knowledge_type": "boundary",
            "scenario": "all",
            "source_document_id": second["id"],
            "source_page": 1,
            "search_text": "never pressure after a refusal",
            "forbidden_acts": ["pressure"],
            "status": "active",
        }
    )
    retrieved = repository.retrieve(
        query="totally unrelated wording",
        relationship_stage="new",
    )
    assert [row["rule_key"] for row in retrieved["boundaries"]] == [
        "respect-boundary"
    ]


def test_conflicting_knowledge_is_review_gated_before_activation():
    engine = _engine()
    repository = KnowledgeRepository(engine, creator_id="creator-a")
    document = repository.ingest(_extracted())
    repository.create_rule(
        {
            "rule_key": "support-first",
            "knowledge_profile": "conversation",
            "knowledge_type": "decision_rule",
            "scenario": "emotional_disclosure",
            "source_document_id": document["id"],
            "source_page": 1,
            "search_text": "validate before asking another question",
            "relationship_stages": ["developing_trust"],
            "recommended_acts": ["validate"],
            "status": "active",
        }
    )
    conflicting = repository.create_rule(
        {
            "rule_key": "skip-validation",
            "knowledge_profile": "conversation",
            "knowledge_type": "decision_rule",
            "scenario": "emotional_disclosure",
            "source_document_id": document["id"],
            "source_page": 1,
            "search_text": "move directly to a new topic",
            "relationship_stages": ["developing_trust"],
            "forbidden_acts": ["validate"],
            "status": "active",
        }
    )

    overview = repository.overview()
    assert conflicting["status"] == "approved"
    assert overview["open_conflicts"] == 1
    with pytest.raises(ValueError, match="resolve rule conflicts"):
        repository.set_rule_status(
            conflicting["id"],
            status="active",
            actor="owner",
        )
    resolved = repository.resolve_conflict(
        overview["conflicts"][0]["id"],
        resolution="The support-first rule wins for this stage.",
        actor="owner",
    )
    assert resolved["status"] == "resolved"
    activated = repository.set_rule_status(
        conflicting["id"],
        status="active",
        actor="owner",
    )
    assert activated["status"] == "active"


def test_pdf_ingestion_rejects_invalid_and_unreadable_without_external_ocr():
    with pytest.raises(KnowledgeIngestionError, match="not a valid PDF"):
        extract_pdf(b"not-a-pdf", filename="playbook.pdf")

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    from io import BytesIO

    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(KnowledgeIngestionError, match="OCR is not performed"):
        extract_pdf(buffer.getvalue(), filename="scanned.pdf")


def test_global_diversity_rejects_repeated_creator_template():
    result = GlobalDiversityGate().evaluate(
        "that makes me happy to hear, just promise me you'll take it slow",
        recent_fan_messages=[],
        recent_creator_messages=[
            "that makes me happy to hear, just promise me you'll take it slow"
        ],
    )
    assert result.approved is False
    assert "repeated_opener" in result.rejection_codes


def test_diversity_does_not_treat_fan_structure_as_creator_template_history():
    result = GlobalDiversityGate().evaluate(
        "i can see why that felt hard today",
        recent_fan_messages=["i have been working late every day"],
        recent_creator_messages=[],
    )
    assert result.approved is True


def test_memory_v3_is_source_backed_bounded_and_always_returns_boundaries():
    engine = _engine()
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a", "fan-a", "chat-a"
    )
    repository = FanMemoryV2Repository(engine)
    writer = ExtractedMemoryWriter(repository)
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    written = writer.write(
        creator_id="creator-a",
        fan_id="fan-a",
        source_message_id="message-9",
        source_timestamp=now,
        extracted={
            "memory_candidates": [
                {
                    "type": "preference",
                    "value": "likes running before work",
                    "confidence": 0.9,
                    "importance": 0.8,
                    "sensitivity_class": "standard",
                },
                {
                    "type": "boundary",
                    "value": "does not want pet names",
                    "confidence": 0.2,
                    "importance": 0.1,
                },
                {
                    "type": "uncertain_hypothesis",
                    "value": "may prefer quiet evenings",
                    "confidence": 0.95,
                    "importance": 0.4,
                    "temporary_days": 14,
                },
                {
                    "type": "correction",
                    "value": "works nights now",
                    "confidence": 1.0,
                },
            ]
        },
    )
    retrieved = MemoryRetrieverV3(engine, creator_id="creator-a").retrieve(
        fan_id="fan-a",
        query="you said you like running before work",
        now=now,
    )
    durable = repository.relevant(
        creator_id="creator-a", fan_id="fan-a", limit=20
    )

    assert written == 3
    assert {item["type"] for item in retrieved["memories"]} >= {
        "preference",
        "boundary",
    }
    boundary = next(item for item in durable if item["memory_type"] == "boundary")
    uncertain = next(
        item for item in durable if item["memory_type"] == "uncertain_hypothesis"
    )
    assert boundary["confidence"] == 1.0
    assert uncertain["confidence"] <= 0.69
    assert uncertain["expires_at"] is not None


def test_memory_v3_reports_conflicts_without_putting_conflicting_values_in_prompt():
    engine = _engine()
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a", "fan-a", "chat-a"
    )
    repository = FanMemoryV2Repository(engine)
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    writer = ExtractedMemoryWriter(repository)
    assert writer.write(
        creator_id="creator-a",
        fan_id="fan-a",
        source_message_id="message-conflict",
        source_timestamp=now,
        extracted={
            "memory_candidates": [
                {
                    "type": "identity_fact",
                    "value": "works nights",
                    "confidence": 0.95,
                    "importance": 0.8,
                }
            ]
        },
    ) == 1
    with engine.begin() as connection:
        from src.conversation.brain2_schema import FAN_MEMORIES_V2

        connection.execute(
            FAN_MEMORIES_V2.update()
            .where(FAN_MEMORIES_V2.c.creator_id == "creator-a")
            .where(FAN_MEMORIES_V2.c.fan_id == "fan-a")
            .values(contradiction_status="conflicted")
        )

    retrieved = MemoryRetrieverV3(engine, creator_id="creator-a").retrieve(
        fan_id="fan-a",
        query="when do you work?",
        now=now,
    )

    assert retrieved["conflicts_excluded"] == 1
    assert retrieved["memories"] == []


def test_explicit_correction_supersedes_stale_fact_across_memory_types():
    engine = _engine()
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a", "fan-a", "chat-a"
    )
    repository = FanMemoryV2Repository(engine)
    writer = ExtractedMemoryWriter(repository)
    first = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert writer.write(
        creator_id="creator-a",
        fan_id="fan-a",
        source_message_id="message-old",
        source_timestamp=first,
        extracted={
            "memory_candidates": [
                {
                    "type": "identity_fact",
                    "value": "works days",
                    "confidence": 0.95,
                    "importance": 0.8,
                    "contradiction_key": "work_schedule",
                }
            ]
        },
    ) == 1
    assert writer.write(
        creator_id="creator-a",
        fan_id="fan-a",
        source_message_id="message-correction",
        source_timestamp=first + timedelta(minutes=1),
        extracted={
            "memory_candidates": [
                {
                    "type": "correction",
                    "value": "works nights now",
                    "confidence": 1.0,
                    "importance": 1.0,
                    "contradiction_key": "work_schedule",
                }
            ]
        },
    ) == 1

    active = repository.relevant(
        creator_id="creator-a", fan_id="fan-a", limit=20
    )
    assert [row["display_value"] for row in active] == ["works nights now"]
    stale = next(
        row
        for row in (
            repository.get(memory_id)
            for memory_id in range(1, 3)
        )
        if row and row["display_value"] == "works days"
    )
    assert stale["status"] == "superseded"


def test_outcome_observation_measures_more_than_reply_existence():
    observed = observe_reply("actually, that sounded scripted and made me uncomfortable")
    score = composite_quality(
        {
            **observed,
            "fan_replied": True,
            "meaningful_reply": True,
            "continued_three_turns": False,
            "returned_within_24h": True,
        }
    )
    assert observed["reply_length"] > 0
    assert observed["semantic_substance"] > 0
    assert observed["correction_signal"] is True
    assert observed["bot_suspicion"] is True
    assert score < 0


def test_shadow_state_observation_makes_zero_model_calls_and_zero_outbox_writes():
    engine = _engine()
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    inbound, created = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-a",
        platform_message_id="provider-message-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="my interview is tomorrow and i feel nervous",
        provider_created_at=utcnow(),
    )
    assert created is True

    class PlannerMustNotRun:
        model = "must-not-run"

        def generate(self, *args, **kwargs):
            raise AssertionError("planner must stay off")

    class MessageStore:
        def get_recent_creator_messages(self, creator_id, limit):
            return []

    service = ConversationIntelligenceV3Service(
        engine=engine,
        creator_id="creator-a",
        settings=V3RuntimeSettings(
            relationship_state_v2_mode="shadow",
            strategy_planner_v2_mode="off",
            allow_live_send=False,
        ),
        planner=PlannerMustNotRun(),
        message_store=MessageStore(),
        shadow_percent=100,
    )
    assert service.submit(
        inbound_id=inbound.id,
        inbound_message_id="provider-message-1",
        fan_id="fan-a",
        trigger_kind="unread",
        provider_created_at=inbound.provider_created_at,
        current_decision_id=None,
        context={"fan_message": inbound.content},
    ) is True
    service.wait_for_idle()
    status = service.safe_status()
    quality = service.intelligence.quality_overview()
    insight = service.intelligence.fan_insight(fan_id="fan-a")
    service.shutdown()

    with engine.connect() as connection:
        outbox_count = connection.execute(
            select(func.count()).select_from(OUTBOX_MESSAGES)
        ).scalar_one()
    assert outbox_count == 0
    assert status["live_send_authority"] is False
    assert quality["outcomes"]["observed"] == 0
    assert insight["facts"] == []


def test_live_decision_returns_candidate_without_outbox_or_provider_capability():
    engine = _engine()
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    inbound, created = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-a",
        platform_message_id="provider-live-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="my interview is tomorrow and i feel nervous",
        provider_created_at=utcnow(),
    )
    assert created is True

    plan = HighEQPlan.model_validate(
        _planner_payload(
            [
                "that interview has been sitting heavy on u",
                "nervous makes sense when it matters this much",
            ]
        )
    )

    class Planner:
        model = "deepseek-v4-flash"
        diversity = GlobalDiversityGate()

        def generate(self, *args, **kwargs):
            return PlannerResult(
                plan=plan,
                assessments=(),
                selected_message=plan.candidates[0].message,
                selected_candidate_id=plan.candidates[0].candidate_id,
                rejection_codes=(),
                model_calls=1,
                latency_ms=25,
                prompt_tokens=120,
                completion_tokens=30,
                estimated_cost=0.000025,
                selection_mode="model_candidate",
                fallback_reason=None,
                requires_operator_review=False,
            )

    class MessageStore:
        def get_recent_creator_messages(self, creator_id, limit):
            return []

    clock = [datetime(2026, 8, 2, tzinfo=timezone.utc)]
    service = ConversationIntelligenceV3Service(
        engine=engine,
        creator_id="creator-a",
        settings=V3RuntimeSettings(
            playbook_engine_mode="live",
            relationship_state_v2_mode="live",
            memory_retrieval_v3_mode="live",
            strategy_planner_v2_mode="live",
            global_diversity_mode="live",
            outcome_learning_mode="observe",
            multi_bubble_mode="shadow",
            allow_live_send=True,
            live_percent=100,
            max_live_percent=100,
            max_daily_cost=10,
        ),
        planner=Planner(),
        message_store=MessageStore(),
        shadow_percent=100,
        clock=lambda: clock[0],
    )
    decision = service.decide_live(
        inbound_id=inbound.id,
        inbound_message_id="provider-live-1",
        fan_id="fan-a",
        trigger_kind="unread",
        provider_created_at=inbound.provider_created_at,
        context={
            "fan_message": inbound.content,
            "history": "",
            "recent_fan_messages": [],
            "recent_creator_messages": [],
        },
    )

    assert decision is not None
    assert decision.message == "that interview has been sitting heavy on u"
    assert service.decide_live(
        inbound_id=inbound.id,
        inbound_message_id="provider-live-1",
        fan_id="fan-a",
        trigger_kind="stalled",
        provider_created_at=inbound.provider_created_at,
        context={"fan_message": inbound.content},
    ) is None
    with engine.connect() as connection:
        outbox_count = connection.execute(
            select(func.count()).select_from(OUTBOX_MESSAGES)
        ).scalar_one()
        live_run = connection.execute(
            select(CONVERSATION_INTELLIGENCE_RUNS).where(
                CONVERSATION_INTELLIGENCE_RUNS.c.id
                == decision.intelligence_run_id
            )
        ).mappings().one()
    live_cost_since = service.intelligence.live_cost_since
    service.intelligence.live_cost_since = lambda _since: 10.0
    assert service.can_decide_live(
        fan_id="fan-a",
        trigger_kind="unread",
    ) is False
    service.intelligence.live_cost_since = live_cost_since
    service.record_live_failure()
    service.record_live_failure()
    service.record_live_failure()
    assert service.can_decide_live(
        fan_id="fan-a",
        trigger_kind="unread",
    ) is False
    clock[0] += timedelta(minutes=2, seconds=1)
    assert service.can_decide_live(
        fan_id="fan-a",
        trigger_kind="unread",
    ) is True
    service.record_live_quality_failure()
    assert service.safe_status()["live_circuit_state"] == "closed"
    status = service.safe_status()
    service.shutdown()

    assert outbox_count == 0
    assert live_run["shadow"] is False
    assert live_run["model"] == "deepseek-v4-flash"
    assert status["live_send_authority"] is True
    assert status["outbox_write_capability"] is False
    assert status["provider_write_capability"] is False
    assert status["live_circuit_open"] is False


def test_frozen_suite_has_204_sanitized_cases_and_all_required_scenarios():
    cases = frozen_cases()
    assert len(cases) == FROZEN_CASE_COUNT == 204
    assert len(FROZEN_SUITE_FINGERPRINT) == 64
    assert {case["scenario"] for case in cases} == {seed.scenario for seed in SEEDS}
    required = {
        "recent_conversation",
        "newest_combined_fan_turn",
        "relevant_memory",
        "relationship_state",
        "expected_act_range",
        "required_observations",
        "forbidden_mistakes",
    }
    assert all(required <= set(case) for case in cases)
    serialized = str(cases).casefold()
    assert "provider_account_id" not in serialized
    assert "username" not in serialized
    manifest = json.loads(
        Path("evals/conversation_intelligence_v3_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["suite_fingerprint"] == FROZEN_SUITE_FINGERPRINT
    assert manifest["current_production_reference"]["score"] == 64
    assert manifest["identical_case_current_candidate_baseline"]["score"] is None
    assert manifest["promotion_eligible"] is False


def test_frozen_evaluator_requires_complete_blinded_evidence_and_never_promotes():
    rows = [
        {
            "case_id": case["case_id"],
            "response": f"specific synthetic response {index}",
            "newest_turn_relevant": True,
            "unsupported_creator_facts": 0,
            "direct_question_answered": True,
            "structure_fingerprint": f"structure-{index}",
            "unnecessary_question_ending": False,
            "generic_fallback": False,
            "latency_ms": 2_000,
            "model_calls": 1,
            "path": "fast",
            "model": "deepseek-v4-flash",
            "safety_failure": False,
        }
        for index, case in enumerate(frozen_cases())
    ]
    pending = evaluate_candidate_artifact(rows)
    assert all(pending["gates"].values())
    assert pending["blinded"]["gate_passed"] is False
    assert pending["frozen_thresholds_pass"] is False
    assert pending["promotion_eligible"] is False

    reviewed = evaluate_candidate_artifact(
        rows,
        blinded_reviews=[
            {"case_id": case["case_id"], "winner": "candidate"}
            for case in frozen_cases()
        ],
    )
    assert reviewed["blinded"]["candidate_preference_rate"] == 1.0
    assert reviewed["blinded"]["gate_passed"] is True

    invalid = [dict(row) for row in rows]
    invalid[0]["newest_turn_relevant"] = "false"
    with pytest.raises(ValueError, match="non-boolean"):
        evaluate_candidate_artifact(invalid)

    zero_call = [dict(row) for row in rows]
    zero_call[0]["model_calls"] = 0
    zero_call_summary = evaluate_candidate_artifact(zero_call)
    assert zero_call_summary["gates"]["model_call_ceiling"] is False

    generic = [dict(row) for row in rows]
    for row in generic[:7]:
        row["response"] = "aww babe 🥺 tell me more"
    generic_summary = evaluate_candidate_artifact(generic)
    assert generic_summary["metrics"]["generic_opening_rate"] > 0.03
    assert generic_summary["gates"]["generic_openings"] is False
    assert reviewed["frozen_thresholds_pass"] is True
    assert reviewed["promotion_eligible"] is False
    assert pending_evaluation_summary()["promotion_eligible"] is False


def test_frozen_evaluator_rejects_partial_artifacts():
    with pytest.raises(ValueError, match="every case exactly once"):
        evaluate_candidate_artifact([])
