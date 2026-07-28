import time

from sqlalchemy import func, select

from src.conversation.advanced import AdvancedBrainDecisionService
from src.conversation.brain2 import BrainRuntimeSettings
from src.conversation.shadow import (
    ProviderContractError,
    ProviderDiagnostic,
    StrategicResult,
)
from src.persistence.database import create_database_engine
from src.persistence.schema import OUTBOX_MESSAGES, metadata
from src.persistence.state import ConversationStateRepository


class SuccessfulAnalyzer:
    model = "deepseek-v4-flash"

    def analyze_fast(self, context):
        return StrategicResult(
            planner={
                "fan_state": "engaged",
                "objective": "maintain",
                "tactic": "direct_answer",
                "open_thread": "weekend",
                "confidence": 0.8,
            },
            candidates=[{"style": "improved_fast", "message": "tell me more about that"}],
            judge={"winner": 0, "all_rejected": False, "confidence": 0.8},
            selected_candidate="tell me more about that",
            model_calls=1,
            provider_attempts=1,
            prompt_tokens=100,
            completion_tokens=12,
            total_tokens=112,
        )

    def analyze(self, context):
        return self.analyze_fast(context)


class FailingAnalyzer(SuccessfulAnalyzer):
    def analyze_fast(self, context):
        raise ProviderContractError(
            "fast_json_invalid",
            ProviderDiagnostic(
                stage="fast",
                error_category="json_invalid",
                attempt_count=1,
            ),
        )


class SlowAnalyzer(SuccessfulAnalyzer):
    def analyze_fast(self, context):
        time.sleep(0.05)
        return super().analyze_fast(context)


def _engine():
    engine = create_database_engine(
        "sqlite:///:memory:",
        environment={"APP_ENV": "test"},
    )
    metadata.create_all(engine)
    ConversationStateRepository(engine).ensure_creator("creator-a")
    return engine


def _settings(**changes):
    values = {
        "mode": "advanced",
        "allow_advanced_send": True,
        "live_percent": 100,
        "max_live_percent": 100,
        "max_strategic_calls_per_hour": 100,
        "max_strategic_calls_per_day": 100,
        "live_timeout_seconds": 1.0,
    }
    values.update(changes)
    return BrainRuntimeSettings(**values)


def _context(message="hey"):
    return {
        "fan_message": message,
        "history": "Fan: hey",
        "recent_creator_messages": [],
        "question_streak": 0,
        "pet_name_streak": 0,
        "hard_boundaries": [],
    }


def test_advanced_service_returns_decision_but_never_writes_outbox():
    engine = _engine()
    settings = _settings()
    service = AdvancedBrainDecisionService(
        engine=engine,
        creator_id="creator-a",
        analyzer=SuccessfulAnalyzer(),
        settings_provider=lambda: settings,
    )

    outcome = service.decide(
        fan_id="fan-a",
        trigger_kind="unread",
        context=_context(),
    )

    assert outcome.succeeded is True
    assert outcome.decision.final_message == "tell me more about that"
    assert outcome.route == "fast"
    assert outcome.provider_attempts == 1
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(OUTBOX_MESSAGES)
        ).scalar_one() == 0
    service.shutdown()


def test_advanced_service_returns_typed_provider_failure_for_current_fallback():
    engine = _engine()
    settings = _settings()
    service = AdvancedBrainDecisionService(
        engine=engine,
        creator_id="creator-a",
        analyzer=FailingAnalyzer(),
        settings_provider=lambda: settings,
    )

    outcome = service.decide(
        fan_id="fan-a",
        trigger_kind="unread",
        context=_context(),
    )

    assert outcome.succeeded is False
    assert outcome.fallback_reason == "fast_json_invalid"
    assert outcome.decision is None
    service.shutdown()


def test_advanced_service_rejects_unsafe_candidate_without_fallback_message():
    engine = _engine()
    settings = _settings()
    analyzer = SuccessfulAnalyzer()
    analyzer.analyze_fast = lambda context: StrategicResult(
        planner={"objective": "maintain", "tactic": "direct_answer"},
        candidates=[{"style": "fast", "message": "unlock this for $20"}],
        judge={"winner": 0, "all_rejected": False},
        selected_candidate="unlock this for $20",
        model_calls=1,
    )
    service = AdvancedBrainDecisionService(
        engine=engine,
        creator_id="creator-a",
        analyzer=analyzer,
        settings_provider=lambda: settings,
    )

    outcome = service.decide(
        fan_id="fan-a",
        trigger_kind="unread",
        context=_context(),
    )

    assert outcome.succeeded is False
    assert outcome.fallback_reason == "quality_gate_rejected"
    assert "sales_or_ppv" in outcome.gate_reason_codes
    service.shutdown()


def test_advanced_timeout_returns_control_without_sending():
    engine = _engine()
    settings = _settings(live_timeout_seconds=0.01)
    service = AdvancedBrainDecisionService(
        engine=engine,
        creator_id="creator-a",
        analyzer=SlowAnalyzer(),
        settings_provider=lambda: settings,
    )

    outcome = service.decide(
        fan_id="fan-a",
        trigger_kind="unread",
        context=_context(),
    )

    assert outcome.succeeded is False
    assert outcome.fallback_reason == "advanced_timeout"
    service.shutdown()


def test_runtime_rollback_invalidates_inflight_result_before_authority_return():
    engine = _engine()
    snapshots = [_settings(), _settings(mode="current", live_percent=0)]
    service = AdvancedBrainDecisionService(
        engine=engine,
        creator_id="creator-a",
        analyzer=SuccessfulAnalyzer(),
        settings_provider=lambda: snapshots.pop(0) if len(snapshots) > 1 else snapshots[0],
    )

    outcome = service.decide(
        fan_id="fan-a",
        trigger_kind="unread",
        context=_context(),
    )

    assert outcome.succeeded is False
    assert outcome.fallback_reason == "stale_authority_after_rollback"
    service.shutdown()
