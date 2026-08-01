from datetime import datetime, timezone
import json
from unittest.mock import MagicMock

import httpx
import pytest

from sqlalchemy import func, select

from src.conversation.brain2 import BrainRuntimeSettings
from src.conversation.shadow import (
    CONTRACT_EXAMPLES,
    DeepSeekStrategicAnalyzer,
    MAX_INSTRUCTION_CONTEXT_CHARS,
    ProviderContractError,
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


def test_strategic_analyzer_uses_40k_instruction_context():
    marker = "instruction-after-eight-thousand"
    instructions = ("x" * 25_000) + marker + ("y" * 20_000)

    safe = DeepSeekStrategicAnalyzer._safe_context(
        {"chat_instructions": instructions}
    )

    assert marker in safe["chat_instructions"]
    assert len(safe["chat_instructions"]) == MAX_INSTRUCTION_CONTEXT_CHARS


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
                    "content": "```json\n"
                    + json.dumps(
                        {
                            "fan_state": "engaged",
                            "objective": "maintain",
                            "tactic": "direct_answer",
                            "open_thread": None,
                            "confidence": 0.8,
                            "message": "hey, how are you?",
                        }
                    )
                    + "\n```"
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



def _provider_response(content, *, finish_reason="stop", usage=None):
    response = MagicMock(spec=httpx.Response)
    response.raise_for_status.return_value = None
    response.status_code = 200
    response.json.return_value = {
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": content},
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        },
    }
    return response


def _fast_payload(**changes):
    payload = {
        "fan_state": "engaged",
        "objective": "maintain",
        "tactic": "direct_answer",
        "open_thread": None,
        "confidence": 0.8,
        "message": "hey, how are you?",
    }
    payload.update(changes)
    return json.dumps(payload)


def test_fast_contract_uses_json_mode_and_exact_schema_example(monkeypatch):
    post = MagicMock(return_value=_provider_response(_fast_payload()))
    monkeypatch.setattr(httpx, "post", post)

    DeepSeekStrategicAnalyzer(
        api_key="secret",
        model="deepseek-v4-flash",
    ).analyze_fast({"fan_message": "hey"})

    request = post.call_args.kwargs["json"]
    assert request["response_format"] == {"type": "json_object"}
    assert '"fan_state"' in request["messages"][0]["content"]
    assert '"message"' in request["messages"][0]["content"]


def test_fast_contract_classifies_empty_output_and_retries_once(monkeypatch):
    post = MagicMock(
        side_effect=[
            _provider_response(""),
            _provider_response(""),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "fast_output_empty"
    assert error.value.diagnostic.attempt_count == 2
    assert post.call_count == 2


def test_fast_contract_classifies_truncation_and_retries_once(monkeypatch):
    post = MagicMock(
        side_effect=[
            _provider_response('{"message":"hel', finish_reason="length"),
            _provider_response('{"message":"hel', finish_reason="length"),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "output_truncated"
    assert error.value.diagnostic.finish_reason == "length"
    assert post.call_count == 2


def test_fast_contract_rejects_prefixed_or_trailing_prose(monkeypatch):
    post = MagicMock(
        return_value=_provider_response("Here is JSON: " + _fast_payload())
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "fast_json_invalid"
    assert post.call_count == 1


def test_fast_contract_repairs_valid_json_with_schema_errors_once(monkeypatch):
    post = MagicMock(
        side_effect=[
            _provider_response(_fast_payload(confidence="high")),
            _provider_response(_fast_payload(confidence=0.8)),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    result = DeepSeekStrategicAnalyzer(
        api_key="secret",
        model="deepseek-v4-flash",
    ).analyze_fast({"fan_message": "hey"})

    assert result.selected_candidate == "hey, how are you?"
    assert result.provider_attempts == 2
    assert result.repair_calls == 1
    assert post.call_count == 2


def test_fast_contract_does_not_loop_when_schema_repair_fails(monkeypatch):
    post = MagicMock(
        side_effect=[
            _provider_response(_fast_payload(confidence="high")),
            _provider_response(_fast_payload(confidence="still-high")),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "fast_schema_invalid"
    assert error.value.diagnostic.attempt_count == 2
    assert post.call_count == 2


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.TimeoutException("timeout"), "provider_timeout"),
        (429, "provider_rate_limited"),
        (503, "provider_server_error"),
    ],
)
def test_retryable_provider_failures_retry_once(
    monkeypatch,
    failure,
    expected,
):
    if isinstance(failure, int):
        failed = MagicMock(spec=httpx.Response)
        failed.status_code = failure
        failed.raise_for_status.side_effect = httpx.HTTPStatusError(
            "provider error",
            request=httpx.Request("POST", "https://api.deepseek.com"),
            response=httpx.Response(failure),
        )
        failure = failed
    post = MagicMock(side_effect=[failure, failure])
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
            retry_jitter_seconds=0,
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == expected
    assert error.value.diagnostic.attempt_count == 2
    assert post.call_count == 2


def test_candidates_contract_requires_exact_styles_and_count(monkeypatch):
    planner = {
        "fan_emotion": "neutral",
        "fan_energy": "medium",
        "fan_intent": "chat",
        "relationship_stage": "new",
        "evidence_labels": [],
        "confidence": 0.8,
        "objective": "maintain",
        "tactic": "direct_answer",
        "active_thread": None,
        "must_reference": [],
        "must_avoid": [],
        "target_length": "short",
        "candidate_styles": [
            "warm_attentive",
            "playful_light",
            "direct_confident",
        ],
        "risk_flags": [],
    }
    invalid = {
        "candidates": [
            {"style": "warm_attentive", "message": "one"},
            {"style": "playful_light", "message": "two"},
        ]
    }
    post = MagicMock(
        side_effect=[
            _provider_response(json.dumps(planner)),
            _provider_response(json.dumps(invalid)),
            _provider_response(json.dumps(invalid)),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze({"fan_message": "hey"})

    assert error.value.code == "candidates_schema_invalid"
    assert post.call_count == 3


def test_judge_contract_rejects_out_of_range_winner():
    analyzer = DeepSeekStrategicAnalyzer(
        api_key="secret",
        model="deepseek-v4-flash",
    )
    with pytest.raises(ProviderContractError) as error:
        analyzer._validate_contract(
            "judge",
            {
                "scores": [],
                "hard_failures": [],
                "winner": 3,
                "confidence": 0.8,
                "all_rejected": False,
            },
            context={"candidate_count": 3},
        )

    assert error.value.code == "judge_schema_invalid"



def test_strategic_provider_attempts_never_exceed_per_turn_budget(monkeypatch):
    planner = CONTRACT_EXAMPLES["planner"]
    invalid_candidates = {"candidates": []}
    valid_candidates = CONTRACT_EXAMPLES["candidates"]
    invalid_judge = {
        "scores": [],
        "hard_failures": [],
        "winner": 9,
        "confidence": 0.8,
        "all_rejected": False,
    }
    post = MagicMock(
        side_effect=[
            _provider_response(json.dumps(planner)),
            _provider_response(json.dumps(invalid_candidates)),
            _provider_response(json.dumps(valid_candidates)),
            _provider_response(json.dumps(invalid_judge)),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze(
            {
                "fan_message": "hey",
                "_max_provider_attempts_per_turn": 4,
            }
        )

    assert error.value.code == "per_turn_call_cap"
    assert post.call_count == 4



def test_schema_repair_can_be_disabled_per_turn(monkeypatch):
    post = MagicMock(
        return_value=_provider_response(_fast_payload(confidence="high"))
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze_fast(
            {
                "fan_message": "hey",
                "_json_repair_attempts": 0,
            }
        )

    assert error.value.code == "fast_schema_invalid"
    assert post.call_count == 1



def test_one_provider_call_never_retries_and_repairs(monkeypatch):
    post = MagicMock(
        side_effect=[
            httpx.TimeoutException("timeout"),
            _provider_response(_fast_payload(confidence="high")),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
            retry_jitter_seconds=0,
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "fast_schema_invalid"
    assert post.call_count == 2



def test_provider_network_error_retries_once(monkeypatch):
    post = MagicMock(
        side_effect=[
            httpx.ConnectError("connection failed"),
            httpx.ConnectError("connection failed"),
        ]
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
            retry_jitter_seconds=0,
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "provider_network_error"
    assert post.call_count == 2


def test_unexpected_finish_reason_is_classified_before_parsing(monkeypatch):
    post = MagicMock(
        return_value=_provider_response(
            _fast_payload(),
            finish_reason="content_filter",
        )
    )
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(ProviderContractError) as error:
        DeepSeekStrategicAnalyzer(
            api_key="secret",
            model="deepseek-v4-flash",
        ).analyze_fast({"fan_message": "hey"})

    assert error.value.code == "provider_content_filtered"
    assert error.value.diagnostic.finish_reason == "content_filter"
