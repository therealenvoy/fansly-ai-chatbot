from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import create_engine, insert, select

from src.human_delivery.contracts import HumanDeliveryDecision
from src.human_delivery.guide import DEFAULT_CONVERSATION_GUIDE
from src.human_delivery.documents import PromptCompiler
from src.human_delivery.planner import HumanDeliveryPlanner
from src.human_delivery.repository import (
    DocumentRepository,
    FanTurnRepository,
    HumanResponsePlanRepository,
)
from src.human_delivery.settings import HumanDeliverySettings
from src.human_delivery.schema import (
    FAN_TURN_INBOUND_LINKS,
    HUMAN_RESPONSE_BUBBLES,
    HUMAN_RESPONSE_PLANS,
)
from src.persistence.schema import (
    CONVERSATION_DECISIONS,
    CREATORS,
    INBOUND_MESSAGES,
    metadata,
)


def _engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(CREATORS).values(
                id="creator-a",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    return engine


def _inbound(engine, *, message_id, content, created_at):
    with engine.begin() as connection:
        result = connection.execute(
            insert(INBOUND_MESSAGES).values(
                creator_id="creator-a",
                platform_message_id=message_id,
                fan_id="fan-a",
                chat_id="chat-a",
                content=content,
                trigger_kind="unread",
                provider_created_at=created_at,
                observed_at=created_at,
                available_at=created_at,
                status="pending",
                attempt_count=0,
            )
        )
    return int(result.inserted_primary_key[0])


def _decision():
    payload = {
        "understanding": {
            "language": "en",
            "fan_emotion": "playful",
            "relationship_stage": "warm",
            "unresolved_topic": None,
        },
        "strategy": {
            "primary_act": "answer",
            "secondary_act": "callback",
            "should_ask_question": False,
            "safety_class": "conversation_only",
        },
        "delivery": {
            "casing_mode": "mostly_lowercase",
            "energy": "medium",
            "bubbles": [
                {"role": "reaction", "text": "wait stop 😭"},
                {"role": "answer", "text": "that is actually so cute"},
            ],
        },
        "memory_updates": [],
        "quality": {
            "facts_grounded": True,
            "sales_intent": False,
            "media_intent": False,
            "ppv_intent": False,
            "tip_intent": False,
            "confidence": 0.9,
        },
    }
    return HumanDeliveryDecision.from_model_output(json.dumps(payload))


def test_document_bootstrap_preserves_legacy_and_keeps_suggestion_draft():
    engine = _engine()
    repository = DocumentRepository(engine, creator_id="creator-a")
    result = repository.bootstrap(
        creator_persona="tone: warm",
        brand_bible="# World\ncats",
        conversation_guide="# Existing\nKeep this exact text.",
        suggested_guide=DEFAULT_CONVERSATION_GUIDE,
    )
    assert result["created"] == 5
    rows = repository.list_documents()
    active = repository.active_documents()
    assert active["conversation_guide"] == "# Existing\nKeep this exact text."
    suggested = [
        row
        for row in rows
        if row["document_type"] == "conversation_guide"
        and row["status"] == "draft"
    ]
    assert len(suggested) == 1
    assert suggested[0]["content"] == DEFAULT_CONVERSATION_GUIDE
    assert repository.bootstrap(
        creator_persona="changed",
        brand_bible="changed",
        conversation_guide="changed",
        suggested_guide="changed",
    ) == {"created": 0, "preserved": True}


def test_fan_turn_groups_inbounds_and_duplicate_link_is_idempotent():
    engine = _engine()
    repository = FanTurnRepository(engine)
    started = datetime.now(timezone.utc)
    first = _inbound(
        engine,
        message_id="synthetic-1",
        content="hey",
        created_at=started,
    )
    second = _inbound(
        engine,
        message_id="synthetic-2",
        content="how r u",
        created_at=started + timedelta(seconds=2),
    )
    turn = repository.add_inbound(first)
    same = repository.add_inbound(second)
    duplicate = repository.add_inbound(first)
    assert same["id"] == turn["id"] == duplicate["id"]
    assert repository.assembled_text(turn["id"]) == "hey\nhow r u"
    with engine.connect() as connection:
        links = connection.execute(
            select(FAN_TURN_INBOUND_LINKS)
        ).mappings().all()
    assert [row["position"] for row in links] == [1, 2]


def test_fan_turn_closes_after_quiet_window_and_survives_repository_restart():
    engine = _engine()
    started = datetime.now(timezone.utc)
    inbound_id = _inbound(
        engine,
        message_id="synthetic-1",
        content="one complete turn",
        created_at=started,
    )
    turn = FanTurnRepository(engine).add_inbound(
        inbound_id,
        debounce_seconds=4,
    )
    closed = FanTurnRepository(engine).close_ready(
        creator_id="creator-a",
        now=turn["quiet_until"] + timedelta(milliseconds=1),
    )
    assert len(closed) == 1
    assert closed[0]["status"] == "ready"


def test_fan_turn_converges_when_older_webhook_arrives_second():
    engine = _engine()
    started = datetime.now(timezone.utc)
    newer = _inbound(
        engine,
        message_id="synthetic-newer",
        content="second",
        created_at=started + timedelta(seconds=2),
    )
    older = _inbound(
        engine,
        message_id="synthetic-older",
        content="first",
        created_at=started,
    )
    repository = FanTurnRepository(engine)
    first_observed = repository.add_inbound(newer)
    converged = repository.add_inbound(older)
    assert converged["id"] == first_observed["id"]
    assert repository.assembled_text(converged["id"]) == "first\nsecond"


def test_shadow_plan_is_idempotent_and_never_writes_outbox():
    engine = _engine()
    started = datetime.now(timezone.utc)
    inbound_id = _inbound(
        engine,
        message_id="synthetic-1",
        content="say something cute",
        created_at=started,
    )
    turn = FanTurnRepository(engine).add_inbound(inbound_id)
    decision = _decision()
    assert decision is not None
    repository = HumanResponsePlanRepository(engine)
    plan, created = repository.save_shadow_plan(
        turn_id=turn["id"],
        creator_id="creator-a",
        fan_id="fan-a",
        decision=decision,
        prompt_fingerprint="a" * 64,
        compilation_report={"included": ["runtime_rules"]},
        model="deepseek-v4-flash",
    )
    same, created_again = repository.save_shadow_plan(
        turn_id=turn["id"],
        creator_id="creator-a",
        fan_id="fan-a",
        decision=decision,
        prompt_fingerprint="a" * 64,
        compilation_report={"included": ["runtime_rules"]},
        model="deepseek-v4-flash",
    )
    assert created is True
    assert created_again is False
    assert same["id"] == plan["id"]
    with engine.connect() as connection:
        bubbles = connection.execute(
            select(HUMAN_RESPONSE_BUBBLES).order_by(
                HUMAN_RESPONSE_BUBBLES.c.bubble_index
            )
        ).mappings().all()
        plans = connection.execute(
            select(HUMAN_RESPONSE_PLANS)
        ).mappings().all()
    assert len(plans) == 1
    assert len(bubbles) == 2
    assert bubbles[0]["available_at"] < bubbles[1]["available_at"]
    assert repository.metrics(creator_id="creator-a")["outbox_writes"] == 0
    assert repository.cancel_plan(plan["id"], reason="manual_creator_send") == 2


def test_shadow_planner_uses_one_model_call_and_never_writes_outbox():
    engine = _engine()
    documents = DocumentRepository(engine, creator_id="creator-a")
    documents.bootstrap(
        creator_persona="tone: warm",
        brand_bible="Never invent facts.",
        conversation_guide="Answer before asking.",
        suggested_guide=DEFAULT_CONVERSATION_GUIDE,
    )
    inbound_id = _inbound(
        engine,
        message_id="synthetic-planner",
        content="i finished it",
        created_at=datetime.now(timezone.utc),
    )
    turn = FanTurnRepository(engine).add_inbound(inbound_id)

    class Provider:
        calls = 0

        def complete_json(self, prompt):
            self.calls += 1
            assert "newest_fan_turn" in prompt
            return json.dumps(
                {
                    "understanding": {
                        "language": "en",
                        "fan_emotion": "happy",
                        "relationship_stage": "warm",
                        "unresolved_topic": None,
                    },
                    "strategy": {
                        "primary_act": "validate",
                        "secondary_act": None,
                        "should_ask_question": False,
                        "safety_class": "conversation_only",
                    },
                    "delivery": {
                        "casing_mode": "mostly_lowercase",
                        "energy": "medium",
                        "bubbles": [
                            {
                                "role": "validation",
                                "text": "That is actually huge",
                            }
                        ],
                    },
                    "memory_updates": [],
                    "quality": {
                        "facts_grounded": True,
                        "sales_intent": False,
                        "media_intent": False,
                        "ppv_intent": False,
                        "tip_intent": False,
                        "confidence": 0.9,
                    },
                }
            )

    provider = Provider()
    planner = HumanDeliveryPlanner(
        documents=documents,
        plans=HumanResponsePlanRepository(engine),
        compiler=PromptCompiler(),
        settings=HumanDeliverySettings.from_mapping(
            {
                "HUMAN_DELIVERY_ENABLED": "true",
                "HUMAN_DELIVERY_MODE": "shadow",
                "HUMAN_DELIVERY_SHADOW_PERCENT": "100",
                "HUMAN_DELIVERY_PROMPT_COMPILER": "true",
            }
        ),
        provider=provider,
        model="stub",
    )
    result = planner.plan_shadow(
        turn_id=turn["id"],
        creator_id="creator-a",
        fan_id="fan-a",
        newest_turn="i finished it",
    )
    assert provider.calls == 1
    assert result["status"] == "shadow_planned"
    assert result["model_calls"] == 1
    assert result["outbox_writes"] == 0


def test_blinded_review_hides_source_until_score_is_stored():
    engine = _engine()
    inbound_id = _inbound(
        engine,
        message_id="synthetic-review",
        content="tell me something",
        created_at=datetime.now(timezone.utc),
    )
    turn = FanTurnRepository(engine).add_inbound(inbound_id)
    with engine.begin() as connection:
        result = connection.execute(
            insert(CONVERSATION_DECISIONS).values(
                inbound_message_id=inbound_id,
                creator_id="creator-a",
                fan_id="fan-a",
                trigger_kind="unread",
                fan_state="warm",
                state_summary="synthetic",
                objective="answer",
                tactic="direct",
                draft="current response",
                critique=[],
                final_message="current response",
                confidence=0.8,
                model="stub",
                authority="current",
                brain_version="current-v1",
                provider_attempts=1,
                model_calls=1,
                retry_calls=0,
                repair_calls=0,
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                estimated_cost=0,
                created_at=datetime.now(timezone.utc),
            )
        )
        decision_id = int(result.inserted_primary_key[0])
    repository = HumanResponsePlanRepository(engine)
    repository.save_shadow_plan(
        turn_id=turn["id"],
        creator_id="creator-a",
        fan_id="fan-a",
        decision=_decision(),
        prompt_fingerprint="b" * 64,
        compilation_report={},
        model="stub",
        current_decision_id=decision_id,
    )
    pair = repository.review_pair(
        creator_id="creator-a",
        reviewer="crm",
    )
    assert pair is not None
    assert set(pair) == {"pair_id", "left", "right"}
    saved = repository.save_review(
        plan_id=pair["pair_id"],
        creator_id="creator-a",
        reviewer="crm",
        scores={"naturalness": {"left": 4, "right": 3}},
        winner="left",
        hard_failures=[],
    )
    assert saved["left_source"] in {"human", "current"}
    assert repository.review_pair(
        creator_id="creator-a",
        reviewer="crm",
    ) is None
