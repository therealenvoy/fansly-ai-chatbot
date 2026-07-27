from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import httpx

from sqlalchemy import func, select

from src.conversation.brain2 import BrainRuntimeSettings
from src.conversation.shadow import (
    DeepSeekStrategicAnalyzer,
    ShadowBrainService,
    StrategicResult,
)
from src.persistence.database import create_database_engine
from src.persistence.pipeline import MessageProcessingRepository
from src.persistence.schema import OUTBOX_MESSAGES, metadata
from src.persistence.state import ConversationStateRepository
from src.conversation.brain2_schema import BRAIN_SHADOW_RUNS


class FakeStrategicAnalyzer:
    def analyze(self, context):
        return StrategicResult(
            planner={"objective": "support", "risk_flags": []},
            candidates=[
                {"style": "warm", "message": "shadow-only candidate"},
                {"style": "playful", "message": "another candidate"},
                {"style": "direct", "message": "direct candidate"},
            ],
            judge={
                "winner": 0,
                "confidence": 0.8,
                "all_rejected": False,
                "scores": [],
            },
            selected_candidate="shadow-only candidate",
            model_calls=3,
        )


def _setup():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_conversation(
        "creator-a",
        "fan-a",
        "chat-a",
    )
    inbound, _ = MessageProcessingRepository(engine).insert_inbound(
        creator_id="creator-a",
        platform_message_id="inbound-1",
        fan_id="fan-a",
        chat_id="chat-a",
        content="I had a rough day",
        provider_created_at=datetime.now(timezone.utc),
    )
    return engine, inbound


def test_shadow_candidate_is_persisted_but_cannot_enter_outbox():
    engine, inbound = _setup()
    service = ShadowBrainService(
        engine=engine,
        creator_id="creator-a",
        settings=BrainRuntimeSettings(
            mode="shadow",
            shadow_sample_percent=100,
        ),
        analyzer=FakeStrategicAnalyzer(),
    )

    run_id = service.submit(
        inbound_id=inbound.id,
        fan_id="fan-a",
        trigger_kind="unread",
        context={
            "fan_message": "I had a rough day",
            "history": "",
            "recent_creator_messages": [],
        },
    )
    service.wait_for_idle()

    assert run_id is not None
    with engine.connect() as connection:
        run = connection.execute(
            select(BRAIN_SHADOW_RUNS).where(
                BRAIN_SHADOW_RUNS.c.id == run_id
            )
        ).mappings().one()
        outbox_count = connection.execute(
            select(func.count()).select_from(OUTBOX_MESSAGES)
        ).scalar_one()
    assert run["status"] == "completed"
    assert run["selected_candidate"] == "shadow-only candidate"
    assert outbox_count == 0
    service.shutdown()


def test_zero_shadow_sample_creates_no_run():
    engine, inbound = _setup()
    service = ShadowBrainService(
        engine=engine,
        creator_id="creator-a",
        settings=BrainRuntimeSettings(
            mode="shadow",
            shadow_sample_percent=0,
        ),
        analyzer=FakeStrategicAnalyzer(),
    )

    assert service.submit(
        inbound_id=inbound.id,
        fan_id="fan-a",
        trigger_kind="unread",
        context={"fan_message": "hey", "history": ""},
    ) is None
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(BRAIN_SHADOW_RUNS)
        ).scalar_one() == 0
    service.shutdown()


def test_shadow_sampling_is_sticky_for_same_fan_and_version():
    engine, _ = _setup()
    settings = BrainRuntimeSettings(
        mode="shadow",
        version="v-sticky",
        shadow_sample_percent=37,
    )
    service = ShadowBrainService(
        engine=engine,
        creator_id="creator-a",
        settings=settings,
        analyzer=FakeStrategicAnalyzer(),
    )

    decisions = {
        service.is_sampled(f"fan-{number}")
        for number in range(1, 20)
    }
    assert service.is_sampled("fan-7") == service.is_sampled("fan-7")
    assert decisions == {False, True}
    service.shutdown()


class FakeTwoSpeedAnalyzer(FakeStrategicAnalyzer):
    def __init__(self):
        self.fast_calls = 0
        self.strategic_calls = 0

    def analyze_fast(self, context):
        self.fast_calls += 1
        return StrategicResult(
            planner={"objective": "continue", "risk_flags": []},
            candidates=[{"style": "fast", "message": "hey, how are you?"}],
            judge={
                "winner": 0,
                "confidence": 0.7,
                "all_rejected": False,
                "evaluation_type": "fast_single_candidate",
            },
            selected_candidate="hey, how are you?",
            model_calls=1,
        )

    def analyze(self, context):
        self.strategic_calls += 1
        return super().analyze(context)


def test_routine_shadow_turn_uses_one_call_fast_path():
    engine, inbound = _setup()
    analyzer = FakeTwoSpeedAnalyzer()
    service = ShadowBrainService(
        engine=engine,
        creator_id="creator-a",
        settings=BrainRuntimeSettings(
            mode="shadow",
            shadow_sample_percent=100,
        ),
        analyzer=analyzer,
    )

    run_id = service.submit(
        inbound_id=inbound.id,
        fan_id="fan-a",
        trigger_kind="unread",
        context={
            "fan_message": "hey",
            "history": "Fan: hey",
            "recent_creator_messages": [],
        },
    )
    service.wait_for_idle()
    with engine.connect() as connection:
        run = connection.execute(
            select(BRAIN_SHADOW_RUNS).where(BRAIN_SHADOW_RUNS.c.id == run_id)
        ).mappings().one()

    assert run["route"] == "fast"
    assert run["model_calls"] == 1
    assert analyzer.fast_calls == 1
    assert analyzer.strategic_calls == 0
    service.shutdown()


def test_per_turn_call_limit_downgrades_strategic_execution_to_fast():
    engine, inbound = _setup()
    analyzer = FakeTwoSpeedAnalyzer()
    service = ShadowBrainService(
        engine=engine,
        creator_id="creator-a",
        settings=BrainRuntimeSettings(
            mode="shadow",
            shadow_sample_percent=100,
            max_model_calls_per_turn=2,
        ),
        analyzer=analyzer,
    )

    run_id = service.submit(
        inbound_id=inbound.id,
        fan_id="fan-a",
        trigger_kind="unread",
        context={
            "fan_message": "I feel alone and upset",
            "history": "",
            "recent_creator_messages": [],
        },
    )
    service.wait_for_idle()
    with engine.connect() as connection:
        run = connection.execute(
            select(BRAIN_SHADOW_RUNS).where(BRAIN_SHADOW_RUNS.c.id == run_id)
        ).mappings().one()

    assert run["route"] == "strategic"
    assert run["model_calls"] == 1
    assert run["gate"]["execution_route"] == "fast"
    assert analyzer.fast_calls == 1
    assert analyzer.strategic_calls == 0
    service.shutdown()


def test_fast_analyzer_serializes_durable_datetime_state(monkeypatch):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "fan_state": "engaged",
                            "objective": "maintain",
                            "tactic": "direct_answer",
                            "open_thread": None,
                            "confidence": 0.8,
                            "message": "hey, how are you?",
                        }
                    )
                }
            }
        ]
    }
    post = MagicMock(return_value=response)
    monkeypatch.setattr(httpx, "post", post)

    result = DeepSeekStrategicAnalyzer(
        api_key="secret",
        model="deepseek-v4-flash",
    ).analyze_fast(
        {
            "fan_message": "hey",
            "conversation_state": {
                "updated_at": datetime.now(timezone.utc),
            },
        }
    )

    assert result.model_calls == 1
    assert result.selected_candidate == "hey, how are you?"
    assert "updated_at" in post.call_args.kwargs["json"]["messages"][1]["content"]
