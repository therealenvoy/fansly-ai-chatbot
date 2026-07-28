from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src.conversation.brain import ConversationDecision
from src.conversation.brain2_repository import (
    BrainBlindedReviewRepository,
    BrainCostCapRepository,
)
from src.conversation.brain2_schema import (
    BRAIN_BLINDED_REVIEWS,
    BRAIN_COMPARISON_PAIRS,
    BRAIN_CONFIGURATION_EVENTS,
)
from src.conversation.repository import ConversationDecisionRepository
from src.conversation.shadow import ShadowBrainService
from src.conversation.brain2 import BrainRuntimeSettings
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import metadata
from src.persistence.state import ConversationStateRepository
from tests.conversation.test_shadow_pipeline import FakeStrategicAnalyzer


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a", "fan-a", "chat-a"
    )
    return engine


def test_daily_cost_ceiling_is_atomic_and_safe_when_disabled():
    engine = _engine()
    repository = BrainCostCapRepository(engine)
    assert repository.reserve(
        creator_id="creator-a", estimated_cost=0.6, daily_limit=1.0
    ) is True
    assert repository.reserve(
        creator_id="creator-a", estimated_cost=0.5, daily_limit=1.0
    ) is False
    assert repository.reserve(
        creator_id="creator-a", estimated_cost=100, daily_limit=0
    ) is True


def test_completed_shadow_run_creates_one_blinded_pair_and_review():
    engine = _engine()
    inbound, _ = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-a",
        platform_message_id="review-inbound",
        fan_id="fan-a",
        chat_id="chat-a",
        content="hey",
        provider_created_at=datetime.now(timezone.utc),
    )
    decision = ConversationDecision(
        fan_state="engaged",
        state_summary="engaged",
        objective="maintain",
        tactic="direct_answer",
        open_thread=None,
        draft="current candidate",
        critique=(),
        final_message="current candidate",
        confidence=0.8,
    )
    decision_id = ConversationDecisionRepository(engine).save(
        inbound_message_id=inbound.id,
        creator_id="creator-a",
        fan_id="fan-a",
        trigger_kind="unread",
        decision=decision,
        model="current",
    )
    service = ShadowBrainService(
        engine=engine,
        creator_id="creator-a",
        settings=BrainRuntimeSettings(
            mode="shadow",
            shadow_sample_percent=100,
        ),
        analyzer=FakeStrategicAnalyzer(),
    )
    service.submit(
        inbound_id=inbound.id,
        fan_id="fan-a",
        trigger_kind="unread",
        current_decision_id=decision_id,
        context={
            "fan_message": "hey",
            "history": "Fan: hey",
            "recent_creator_messages": [],
        },
    )
    service.wait_for_idle()
    with engine.connect() as connection:
        pair = connection.execute(select(BRAIN_COMPARISON_PAIRS)).mappings().one()
    assert {pair["left_source"], pair["right_source"]} == {"current", "advanced"}

    scores = {
        field: {"left": 7, "right": 8}
        for field in BrainBlindedReviewRepository.SCORE_FIELDS
    }
    review_id = BrainBlindedReviewRepository(engine).save_review(
        pair_id=pair["id"],
        creator_id="creator-a",
        reviewer="operator",
        scores=scores,
        winner="right",
        hard_failures=[],
    )
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(BRAIN_BLINDED_REVIEWS)
        ).scalar_one() == 1
        events = connection.execute(
            select(BRAIN_CONFIGURATION_EVENTS).order_by(
                BRAIN_CONFIGURATION_EVENTS.c.id
            )
        ).mappings().all()
    assert review_id > 0
    assert [event["event_type"] for event in events] == ["review_created"]
    assert events[0]["previous_values"] == {}
    assert events[0]["new_values"]["hard_failures"] == []

    updated_review_id = BrainBlindedReviewRepository(engine).save_review(
        pair_id=pair["id"],
        creator_id="creator-a",
        reviewer="operator",
        scores=scores,
        winner="left",
        hard_failures=["right:sales_or_ppv"],
    )
    with engine.connect() as connection:
        events = connection.execute(
            select(BRAIN_CONFIGURATION_EVENTS).order_by(
                BRAIN_CONFIGURATION_EVENTS.c.id
            )
        ).mappings().all()
    assert updated_review_id == review_id
    assert [event["event_type"] for event in events] == [
        "review_created",
        "review_updated",
    ]
    assert events[1]["previous_values"]["winner"] == "right"
    assert events[1]["new_values"]["hard_failures"] == [
        "right:sales_or_ppv"
    ]
    service.shutdown()


def test_blinded_review_rejects_missing_score_dimensions():
    engine = _engine()
    with pytest.raises(ValueError, match="invalid_review_score_fields"):
        BrainBlindedReviewRepository(engine).save_review(
            pair_id=1,
            creator_id="creator-a",
            reviewer="operator",
            scores={},
            winner="tie",
            hard_failures=[],
        )


def test_blinded_review_rejects_unqualified_or_unknown_hard_failures():
    engine = _engine()
    repository = BrainBlindedReviewRepository(engine)
    scores = {
        field: {"left": 7, "right": 8}
        for field in repository.SCORE_FIELDS
    }

    for hard_failure in ("sales_or_ppv", "left:not_a_real_failure"):
        with pytest.raises(ValueError, match="invalid_review_hard_failure"):
            repository.save_review(
                pair_id=1,
                creator_id="creator-a",
                reviewer="operator",
                scores=scores,
                winner="tie",
                hard_failures=[hard_failure],
            )
