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
from src.conversation.intelligence_v3.planner import (
    MAX_CONTEXT_CHARS,
    DeepSeekV3Planner,
    PromptCompilerV3,
)
from src.conversation.intelligence_v3.repository import KnowledgeRepository
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
    frozen_cases,
)
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import CREATORS, OUTBOX_MESSAGES, metadata, utcnow
from src.persistence.state import ConversationStateRepository


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


def test_prompt_compiler_honors_total_budget_and_priority():
    compiler = PromptCompilerV3()
    compiled = compiler.compile(
        {
            "safety": {"conversation_only": True},
            "newest_turn": "newest evidence",
            "recent_history": "h" * 80_000,
            "creator_instructions": "i" * 80_000,
        }
    )

    assert compiled.context["safety"] == {"conversation_only": True}
    assert compiled.context["newest_turn"] == "newest evidence"
    assert compiled.report["used_chars"] <= MAX_CONTEXT_CHARS
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
    assert duplicate.reason == "stale_source"
    assert stale.reason == "stale_source"
    assert callback is not None
    assert callback["subject_key"] == "interview"
    assert infer_callback(
        message="nothing scheduled",
        source_message_id="message-2",
        source_timestamp=when,
    ) is None


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
